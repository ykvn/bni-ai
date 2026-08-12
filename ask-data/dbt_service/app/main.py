"""
FastAPI Web Application serving dbt Semantic Layer & MetricFlow APIs.
Located at: /home/cdsw/ask-data/dbt_service/app/main.py
"""
import os
import sys
import json
import yaml
import subprocess
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# Direct in-process MetricFlow imports
from dbt_semantic_interfaces.implementations.semantic_manifest import PydanticSemanticManifest
from metricflow.manifest.manifest_converter import MetricFlowManifestConverter
from metricflow.engine.metricflow_engine_factory import MetricFlowEngineFactory
from metricflow.protocols.query_param_protocol import MetricFlowQueryRequest

# Ensure ask-data/ root and service directory are in path
_SERVICE_DIR = Path(__file__).resolve().parent.parent
_ASK_DATA_ROOT = _SERVICE_DIR.parent
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))
if str(_SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVICE_DIR))

app = FastAPI(
    title="dbt MetricFlow Semantic Layer API",
    description="Exposes dbt semantic metrics compilation engine for LLM agents",
    version="1.0.0",
)

# Paths
DBT_PROJECT_DIR = _SERVICE_DIR / "dbt_project"
SCHEMA_YAML_PATH = DBT_PROJECT_DIR / "models" / "bni_dbt_schema.yaml"
MANIFEST_PATH = DBT_PROJECT_DIR / "target" / "semantic_manifest.json"
DBT_PROFILES_DIR = Path.home() / ".dbt"
PROFILE_FILE = DBT_PROFILES_DIR / "profiles.yml"

# Global in-memory cache
_ENGINE_CACHE = None
_LAST_YAML_MTIME = 0


class MetricQueryRequest(BaseModel):
    metrics: List[str] = Field(..., description="List of metric names to query")
    group_by: Optional[List[str]] = Field(default=[], description="List of dimension names")
    where: Optional[str] = Field(default=None, description="Optional filter expression")


class MetricQueryResponse(BaseModel):
    status: str
    sql: str
    data: List[Dict[str, Any]] = Field(default=[], description="Empty list as query execution is disabled")


def resolve_cmd(binary_name: str) -> List[str]:
    """Dynamically locates executables in PATH or python bin."""
    import shutil
    found_path = shutil.which(binary_name)
    if found_path:
        return [found_path]
    py_bin = Path(sys.executable).parent / binary_name
    if py_bin.exists():
        return [str(py_bin)]
    user_bin = Path.home() / ".local" / "bin" / binary_name
    if user_bin.exists():
        return [str(user_bin)]
    return [sys.executable, "-m", f"{binary_name}.cli.main"]


def ensure_dbt_manifest():
    """Runs dbt parse if target/semantic_manifest.json is missing or outdated."""
    needs_parse = False
    if not MANIFEST_PATH.exists():
        needs_parse = True
    elif SCHEMA_YAML_PATH.exists() and SCHEMA_YAML_PATH.stat().st_mtime > MANIFEST_PATH.stat().st_mtime:
        needs_parse = True

    if needs_parse:
        print("🔄 Parsing dbt project to regenerate semantic_manifest.json...")
        env = os.environ.copy()
        env["DBT_PROFILES_DIR"] = str(DBT_PROFILES_DIR)
        
        DBT_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        impala_db = os.environ.get("DB_NAME", "test")
        PROFILE_FILE.write_text(f"""
default:
  target: dev
  outputs:
    dev:
      type: postgres
      host: localhost
      port: 5432
      user: dummy
      pass: dummy
      dbname: dummy
      schema: {impala_db}
      threads: 1
""".strip())

        dbt_parse_cmd = resolve_cmd("dbt") + ["parse"]
        parse_proc = subprocess.run(
            dbt_parse_cmd,
            cwd=str(DBT_PROJECT_DIR),
            env=env,
            capture_output=True,
            text=True
        )
        if parse_proc.returncode != 0:
            raise Exception(f"dbt parse failed: {parse_proc.stderr or parse_proc.stdout}")


def get_metricflow_engine():
    """
    Returns a cached MetricFlowEngine loaded directly into Python memory.
    Rebuilds only if bni_dbt_schema.yaml has been modified.
    """
    global _ENGINE_CACHE, _LAST_YAML_MTIME

    current_mtime = SCHEMA_YAML_PATH.stat().st_mtime if SCHEMA_YAML_PATH.exists() else 0

    if _ENGINE_CACHE is None or current_mtime > _LAST_YAML_MTIME:
        ensure_dbt_manifest()

        print("⚡ Loading MetricFlow Engine into RAM...")
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            manifest_dict = json.load(f)

        manifest_dict["adapter_type"] = "postgres"

        semantic_manifest = PydanticSemanticManifest.parse_obj(manifest_dict)
        mf_manifest = MetricFlowManifestConverter().convert_manifest(semantic_manifest)
        
        _ENGINE_CACHE = MetricFlowEngineFactory.create_engine(semantic_manifest=mf_manifest)
        _LAST_YAML_MTIME = current_mtime

    return _ENGINE_CACHE


def load_dbt_catalog() -> Dict[str, Any]:
    """Loads and parses the dbt bni_dbt_schema.yaml file."""
    if not SCHEMA_YAML_PATH.exists():
        return {"semantic_models": [], "metrics": []}
    
    with open(SCHEMA_YAML_PATH, "r") as f:
        return yaml.safe_load(f)


@app.on_event("startup")
def startup_event():
    """Pre-loads the MetricFlow Engine on startup so requests respond instantly."""
    print("🚀 Bootstrapping dbt environment and pre-loading MetricFlow Engine...")
    try:
        get_metricflow_engine()
        print("✅ MetricFlow Engine successfully pre-loaded in memory!")
    except Exception as e:
        print(f"⚠️ Startup pre-load warning: {str(e)}")


@app.get("/healthz")
def health_check():
    return {"status": "healthy", "service": "dbt_service", "dbt_project_found": DBT_PROJECT_DIR.exists()}


@app.get("/api/v1/meta")
def get_semantic_catalog():
    catalog = load_dbt_catalog()
    available_metrics = [
        {
            "name": m.get("name"),
            "label": m.get("label"),
            "description": m.get("description"),
            "synonyms": m.get("meta", {}).get("synonyms", [])
        } for m in catalog.get("metrics", [])
    ]
    available_dimensions = []
    for model in catalog.get("semantic_models", []):
        model_name = model.get("name")
        for dim in model.get("dimensions", []):
            available_dimensions.append({
                "name": f"{model_name}__{dim.get('name')}",
                "description": dim.get("description", ""),
                "meta": dim.get("meta", {})
            })

    return {"metrics": available_metrics, "dimensions": available_dimensions}


@app.post("/api/v1/load", response_model=MetricQueryResponse)
def execute_metric_query(payload: MetricQueryRequest):
    """
    Compiles dynamic MetricFlow metrics into Impala-compatible SQL directly in Python memory.
    """
    try:
        engine = get_metricflow_engine()

        request = MetricFlowQueryRequest.create_with_string_inputs(
            metric_names=payload.metrics,
            group_by_names=payload.group_by or [],
        )

        explain_result = engine.explain(request)
        
        if hasattr(explain_result, "rendered_sql") and explain_result.rendered_sql:
            compiled_sql = explain_result.rendered_sql
        else:
            compiled_sql = str(explain_result)

        compiled_sql = compiled_sql.replace('"', '`')

        return MetricQueryResponse(
            status="success",
            sql=compiled_sql,
            data=[]
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Metric Compilation Failed: {str(e)}")