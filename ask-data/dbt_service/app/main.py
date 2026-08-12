"""
FastAPI Web Application serving dbt Semantic Layer & MetricFlow APIs.
Located at: /home/cdsw/ask-data/dbt_service/app/main.py
"""
import os
import sys
import shutil
import subprocess
import yaml
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
    description="Exposes dbt semantic metrics and Impala execution engine for LLM agents",
    version="1.0.0",
)

# Paths
DBT_PROJECT_DIR = _SERVICE_DIR / "dbt_project"
SCHEMA_YAML_PATH = DBT_PROJECT_DIR / "models" / "bni_dbt_schema.yaml"
MANIFEST_PATH = DBT_PROJECT_DIR / "target" / "semantic_manifest.json"
DBT_PROFILES_DIR = Path.home() / ".dbt"


class MetricQueryRequest(BaseModel):
    metrics: List[str] = Field(..., description="List of metric names to query")
    group_by: Optional[List[str]] = Field(default=[], description="List of dimension names")
    where: Optional[str] = Field(default=None, description="Optional filter expression")


class MetricQueryResponse(BaseModel):
    status: str
    sql: str
    data: List[Dict[str, Any]]


def resolve_cmd(binary_name: str) -> List[str]:
    """Dynamically locates executables in system PATH or python bin."""
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


def load_dbt_catalog() -> Dict[str, Any]:
    if not SCHEMA_YAML_PATH.exists():
        return {"semantic_models": [], "metrics": []}
    with open(SCHEMA_YAML_PATH, "r") as f:
        return yaml.safe_load(f)


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
    try:
        from impala.dbapi import connect

        env = os.environ.copy()
        env["DBT_PROFILES_DIR"] = str(DBT_PROFILES_DIR)

        # 1. AUTO-GENERATE MANIFEST IF MISSING
        if not MANIFEST_PATH.exists():
            dbt_cmd = resolve_cmd("dbt") + ["parse"]
            parse_process = subprocess.run(dbt_cmd, cwd=str(DBT_PROJECT_DIR), env=env, capture_output=True, text=True)
            if parse_process.returncode != 0:
                raise Exception(f"dbt parse failed: {parse_process.stderr or parse_process.stdout}")

        # 2. RUN METRICFLOW EXPLAIN
        mf_cmd = resolve_cmd("mf") + ["query", "--metrics", ",".join(payload.metrics)]
        if payload.group_by:
            mf_cmd.extend(["--group-by", ",".join(payload.group_by)])
        mf_cmd.append("--explain")

        process = subprocess.run(mf_cmd, cwd=str(DBT_PROJECT_DIR), env=env, capture_output=True, text=True)
        if process.returncode != 0:
            raise Exception(f"MetricFlow compilation failed: {process.stderr or process.stdout}")

        output_text = process.stdout.strip()

        # Extract SQL string
        sql_start = -1
        for keyword in ["WITH ", "SELECT "]:
            pos = output_text.upper().find(keyword)
            if pos != -1 and (sql_start == -1 or pos < sql_start):
                sql_start = pos

        compiled_sql = output_text[sql_start:] if sql_start != -1 else output_text

        # 3. EXECUTE COMPILED SQL ON CDW IMPALA
        impala_host = os.environ.get("IMPALA_HOST", "coordinator-impala-vw-cai.apps.dataservices.bni.co.id")
        impala_port = int(os.environ.get("IMPALA_PORT", 443))
        impala_db = os.environ.get("DB_NAME", "test")
        impala_http_path = os.environ.get("IMPALA_HTTP_PATH", "cliservice")
        auth_mech = os.environ.get("IMPALA_AUTH_MECHANISM", "LDAP") 
        impala_user = os.environ.get("IMPALA_USER", "")
        impala_password = os.environ.get("IMPALA_PASSWORD", "")

        conn = connect(
            host=impala_host, 
            port=impala_port, 
            database=impala_db,
            auth_mechanism=auth_mech,
            user=impala_user,
            password=impala_password,
            use_ssl=True, 
            use_http_transport=True, 
            http_path=impala_http_path
        )
        
        cursor = conn.cursor()
        cursor.execute(compiled_sql)

        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        data = [dict(zip(columns, row)) for row in rows]

        return MetricQueryResponse(
            status="success",
            sql=compiled_sql,
            data=data
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Dynamic Query Execution Failed: {str(e)}")