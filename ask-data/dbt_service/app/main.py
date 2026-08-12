"""
FastAPI Web Application serving dbt Semantic Layer & MetricFlow APIs.
Located at: /home/cdsw/ask-data/dbt_service/app/main.py
"""
import os
import sys
import shutil
import subprocess
import yaml
import re
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

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

# Global in-memory engine cache
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


def ensure_metricflow_dummy_adapter():
    """Silently installs 'dbt-postgres' as a dummy dialect compiler for MetricFlow."""
    try:
        import dbt.adapters.postgres
    except ImportError:
        print("📦 Installing dbt-postgres as a dummy dialect compiler for MetricFlow...")
        subprocess.run([sys.executable, "-m", "pip", "install", "dbt-postgres"], check=True)


def ensure_compiler_profile():
    """Writes a clean profiles.yml configuring dbt to compile purely using the dummy Postgres dialect."""
    DBT_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    impala_db = os.environ.get("DB_NAME", "test")

    profile_content = f"""
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
"""
    PROFILE_FILE.write_text(profile_content.strip())


def ensure_manifest_ready():
    """Parses project only if the YAML file changed. Builds a native Postgres semantic manifest."""
    needs_parse = False
    if not MANIFEST_PATH.exists():
        needs_parse = True
    elif SCHEMA_YAML_PATH.exists() and SCHEMA_YAML_PATH.stat().st_mtime > MANIFEST_PATH.stat().st_mtime:
        needs_parse = True

    env = os.environ.copy()
    env["DBT_PROFILES_DIR"] = str(DBT_PROFILES_DIR)

    if needs_parse:
        print("🔄 Schema modified or manifest missing. Running dbt parse...")
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

    # Always ensure adapter_type in semantic_manifest.json is patched to postgres
    if MANIFEST_PATH.exists():
        manifest_text = MANIFEST_PATH.read_text(encoding="utf-8")
        if '"adapter_type": "impala"' in manifest_text:
            patched_manifest = manifest_text.replace('"adapter_type": "impala"', '"adapter_type": "postgres"')
            MANIFEST_PATH.write_text(patched_manifest, encoding="utf-8")


def get_cached_engine():
    """
    Loads the MetricFlow Engine into RAM once using CliConfiguration.
    Rebuilds only if bni_dbt_schema.yaml has been modified.
    """
    global _ENGINE_CACHE, _LAST_YAML_MTIME

    current_mtime = SCHEMA_YAML_PATH.stat().st_mtime if SCHEMA_YAML_PATH.exists() else 0

    if _ENGINE_CACHE is None or current_mtime > _LAST_YAML_MTIME:
        ensure_compiler_profile()
        ensure_metricflow_dummy_adapter()
        ensure_manifest_ready()

        print("⚡ Loading MetricFlow Engine into RAM...")
        old_cwd = os.getcwd()
        try:
            os.chdir(str(DBT_PROJECT_DIR))
            os.environ["DBT_PROFILES_DIR"] = str(DBT_PROFILES_DIR)
            from dbt_metricflow.cli.cli_configuration import CliConfiguration
            cfg = CliConfiguration()
            _ENGINE_CACHE = cfg.mf
            _LAST_YAML_MTIME = current_mtime
            print("✅ MetricFlow Engine cached in memory!")
        finally:
            os.chdir(old_cwd)

    return _ENGINE_CACHE


def load_dbt_catalog() -> Dict[str, Any]:
    """Loads and parses the dbt bni_dbt_schema.yaml file."""
    if not SCHEMA_YAML_PATH.exists():
        return {"semantic_models": [], "metrics": []}
    
    with open(SCHEMA_YAML_PATH, "r") as f:
        return yaml.safe_load(f)


@app.on_event("startup")
def startup_event():
    """Bootstraps environment and pre-loads MetricFlow Engine into RAM on startup."""
    print("🚀 Bootstrapping in-memory dbt environment...")
    os.environ["DBT_PROFILES_DIR"] = str(DBT_PROFILES_DIR)
    try:
        get_cached_engine()
    except Exception as e:
        print(f"⚠️ Pre-load warning on startup: {str(e)}")


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
    """Compiles dynamic MetricFlow metrics into Impala SQL directly in RAM (Sub-100ms response time)."""
    try:
        engine = get_cached_engine()

        from metricflow.protocols.query_param_protocol import MetricFlowQueryRequest
        
        where_constraints = [payload.where] if payload.where else None

        mf_request = MetricFlowQueryRequest.create_with_string_inputs(
            metric_names=payload.metrics,
            group_by_names=payload.group_by or [],
            where_constraint_strings=where_constraints,
        )

        explain_result = engine.explain(mf_request=mf_request)

        # Extract rendered SQL
        if hasattr(explain_result, "rendered_sql") and explain_result.rendered_sql:
            compiled_sql = explain_result.rendered_sql
        elif hasattr(explain_result, "sql") and explain_result.sql:
            compiled_sql = explain_result.sql
        else:
            compiled_sql = str(explain_result)

        # Extract SQL query if preamble logs exist
        match = re.search(r'(?im)^(WITH|SELECT)\b', compiled_sql)
        if match:
            compiled_sql = compiled_sql[match.start():]

        # Format Postgres SQL to Impala Syntax
        compiled_sql = compiled_sql.replace('"', '`')
        
        # Clean up dummy schema/database references
        compiled_sql = re.sub(r'`?dummy`?\.', '', compiled_sql)

        return MetricQueryResponse(
            status="success",
            sql=compiled_sql,
            data=[]
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Metric Compilation Failed: {str(e)}")