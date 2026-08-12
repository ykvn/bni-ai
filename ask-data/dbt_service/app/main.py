"""
FastAPI Web Application serving dbt Semantic Layer & MetricFlow APIs.
Located at: /home/cdsw/ask-data/dbt_service/app/main.py
"""
import os
import sys
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


# --- Request/Response Models ---
class MetricQueryRequest(BaseModel):
    metrics: List[str] = Field(..., description="List of metric names to query (e.g. ['total_principal_amount'])")
    group_by: Optional[List[str]] = Field(default=[], description="List of dimension names (e.g. ['deposits__status'])")
    where: Optional[str] = Field(default=None, description="Optional filter expression")


class MetricQueryResponse(BaseModel):
    status: str
    sql: str
    data: List[Dict[str, Any]]


# --- Helper to load dbt Catalog ---
def load_dbt_catalog() -> Dict[str, Any]:
    """Loads and parses the dbt bni_dbt_schema.yaml file."""
    if not SCHEMA_YAML_PATH.exists():
        return {"semantic_models": [], "metrics": []}
    
    with open(SCHEMA_YAML_PATH, "r") as f:
        return yaml.safe_load(f)


# --- API Routes ---
@app.get("/healthz")
def health_check():
    """Health check endpoint for CML Application router."""
    return {"status": "healthy", "service": "dbt_service", "dbt_project_found": DBT_PROJECT_DIR.exists()}


@app.get("/api/v1/meta")
def get_semantic_catalog():
    """Returns available dbt metrics and dimensions for LLM prompt context."""
    catalog = load_dbt_catalog()
    
    available_metrics = []
    for metric in catalog.get("metrics", []):
        available_metrics.append({
            "name": metric.get("name"),
            "label": metric.get("label"),
            "description": metric.get("description"),
            "synonyms": metric.get("meta", {}).get("synonyms", [])
        })

    available_dimensions = []
    for model in catalog.get("semantic_models", []):
        model_name = model.get("name")
        for dim in model.get("dimensions", []):
            available_dimensions.append({
                "name": f"{model_name}__{dim.get('name')}",
                "description": dim.get("description", "")
            })

    return {
        "metrics": available_metrics,
        "dimensions": available_dimensions
    }


import subprocess

@app.post("/api/v1/load", response_model=MetricQueryResponse)
def execute_metric_query(payload: MetricQueryRequest):
    """
    Executes a metric query against Impala dynamically using dbt's MetricFlow.
    """
    try:
        from impala.dbapi import connect

        # 1. DYNAMICALLY COMPILE SQL VIA DBT METRICFLOW
        # Construct the CLI command: mf query --metrics <m> --group-by <g> --compile
        mf_command = ["mf", "query", "--metrics", ",".join(payload.metrics)]
        
        if payload.group_by:
            mf_command.extend(["--group-by", ",".join(payload.group_by)])
            
        mf_command.append("--compile") # Only compile to SQL, do not execute via CLI

        # Run MetricFlow inside the dbt project directory
        process = subprocess.run(
            mf_command,
            cwd=str(DBT_PROJECT_DIR),
            capture_output=True,
            text=True
        )
        
        if process.returncode != 0:
            raise Exception(f"MetricFlow compilation failed: {process.stderr}")

        # The output is the pure, dynamically generated Impala SQL
        compiled_sql = process.stdout.strip()

        # 2. EXECUTE THE COMPILED SQL ON IMPALA (CDW over 443)
        impala_host = os.environ.get("IMPALA_HOST", "localhost")
        impala_port = int(os.environ.get("IMPALA_PORT", 443))
        impala_http_path = os.environ.get("IMPALA_HTTP_PATH", "cliservice")
        auth_mech = os.environ.get("IMPALA_AUTH_MECHANISM", "LDAP") 
        impala_user = os.environ.get("CDP_USER", "")
        impala_password = os.environ.get("CDP_PASS", "")

        conn = connect(
            host=impala_host, 
            port=impala_port, 
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
            sql=compiled_sql,  # Returns the dynamic SQL for transparency/debugging
            data=data
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Dynamic Query Execution Failed: {str(e)}")