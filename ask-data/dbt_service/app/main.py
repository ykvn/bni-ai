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


def ensure_static_profile():
    """Writes a static profiles.yml containing both Impala and Postgres compilation targets."""
    DBT_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    impala_db = os.environ.get("DB_NAME", "test")
    impala_host = os.environ.get("IMPALA_HOST", "coordinator-impala-vw-cai.apps.dataservices.bni.co.id")
    impala_port = os.environ.get("IMPALA_PORT", "443")
    impala_http_path = os.environ.get("IMPALA_HTTP_PATH", "cliservice")
    impala_user = os.environ.get("CDP_USER", "")
    impala_password = os.environ.get("CDP_PASS", "")

    profile_content = f"""
default:
  target: dev
  outputs:
    dev:
      type: impala
      host: {impala_host}
      port: {impala_port}
      schema: {impala_db}
      auth_type: LDAP
      username: "{impala_user}"
      password: "{impala_password}"
      use_http_transport: true
      http_path: {impala_http_path}
      use_ssl: true
      threads: 1
    mf_compile:
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


def reparse_project_if_needed(env: dict):
    """Parses dbt project only when the schema YAML changes, and pre-patches manifest for MetricFlow."""
    needs_parse = False
    if not MANIFEST_PATH.exists():
        needs_parse = True
    elif SCHEMA_YAML_PATH.exists() and SCHEMA_YAML_PATH.stat().st_mtime > MANIFEST_PATH.stat().st_mtime:
        needs_parse = True

    if needs_parse:
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

        # Pre-patch manifest once after parse so requests don't need disk I/O
        manifest_text = MANIFEST_PATH.read_text(encoding="utf-8")
        patched_manifest = manifest_text.replace('"adapter_type": "impala"', '"adapter_type": "postgres"')
        MANIFEST_PATH.write_text(patched_manifest, encoding="utf-8")


def load_dbt_catalog() -> Dict[str, Any]:
    """Loads and parses the dbt bni_dbt_schema.yaml file."""
    if not SCHEMA_YAML_PATH.exists():
        return {"semantic_models": [], "metrics": []}
    
    with open(SCHEMA_YAML_PATH, "r") as f:
        return yaml.safe_load(f)


@app.on_event("startup")
def startup_event():
    """Bootstraps environment and pre-compiles configuration on app startup."""
    print("🚀 Bootstrapping dbt environment...")
    ensure_static_profile()
    ensure_metricflow_dummy_adapter()


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
    """Compiles dynamic MetricFlow metrics into Impala-compatible SQL without executing against DB."""
    try:
        env = os.environ.copy()
        env["DBT_PROFILES_DIR"] = str(DBT_PROFILES_DIR)
        env["DBT_TARGET"] = "mf_compile"

        # 1. Parse project ONLY if schema YAML changed (pre-patches manifest once)
        reparse_project_if_needed(env)

        # 2. Compile SQL via MetricFlow CLI
        mf_cmd = resolve_cmd("mf") + ["query", "--metrics", ",".join(payload.metrics)]
        if payload.group_by:
            mf_cmd.extend(["--group-by", ",".join(payload.group_by)])
        mf_cmd.append("--explain")

        process = subprocess.run(
            mf_cmd,
            cwd=str(DBT_PROJECT_DIR),
            env=env,
            capture_output=True,
            text=True
        )

        if process.returncode != 0:
            error_msg = process.stderr.strip() or process.stdout.strip()
            raise Exception(f"MetricFlow compilation failed: {error_msg}")

        output_text = process.stdout.strip()

        # Extract compiled SQL block
        match = re.search(r'(?im)^(WITH|SELECT)\b', output_text)
        compiled_sql = output_text[match.start():] if match else output_text

        # Format Postgres identifier quotes to Impala backticks
        compiled_sql = compiled_sql.replace('"', '`')

        return MetricQueryResponse(
            status="success",
            sql=compiled_sql,
            data=[]
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Metric Compilation Failed: {str(e)}")