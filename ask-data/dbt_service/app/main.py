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
import signal
import threading
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# --- ENVIRONMENT & LOGGING SUPPRESSION ---
# Disables MetricFlow / Rich terminal spinners and ANSI colors in CML server logs
os.environ["TERM"] = "dumb"
os.environ["NO_COLOR"] = "1"
os.environ["DBT_USE_COLORS"] = "0"
os.environ["FORCE_COLOR"] = "0"
os.environ["PYTHONUNBUFFERED"] = "1"
os.environ["METRICFLOW_LOG_LEVEL"] = "ERROR"

# --- THREAD-SAFE SIGNAL PATCH ---
# Prevents "signal only works in main thread" error when MetricFlow runs inside FastAPI worker threads
_orig_signal = signal.signal

def _safe_signal(sig, handler):
    try:
        return _orig_signal(sig, handler)
    except ValueError:
        # Safely ignore signal registration attempts from non-main worker threads
        return None

signal.signal = _safe_signal

# --- DISABLE RICH SPINNER ANIMATIONS FOR NON-TTY LOGS ---
# Prevents repeated "Initiating query..." Braille frame entries in non-interactive CML Application Logs
try:
    import rich.console

    # Force rich consoles to render in non-interactive/non-terminal mode
    rich.console.Console.is_terminal = False
    rich.console.Console.is_interactive = False
    
    # Disable status spinner rendering entirely
    def _noop_status(self, *args, **kwargs):
        class DummyStatus:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def start(self): pass
            def stop(self): pass
            def update(self, *args, **kwargs): pass
        return DummyStatus()

    rich.console.Console.status = _noop_status
except Exception:
    pass
# --------------------------------------------------------

# Resolve service directory (used for dbt project paths)
_SERVICE_DIR = Path(__file__).resolve().parent.parent

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

# Global in-memory engine cache flag & thread lock
_CACHE_WARMED = False
_LAST_YAML_MTIME = 0
_MF_LOCK = threading.Lock()


class MetricQueryRequest(BaseModel):
    metrics: List[str] = Field(..., description="List of metric names to query")
    group_by: Optional[List[str]] = Field(default=[], description="List of dimension names")
    where: Optional[str] = Field(default=None, description="Optional filter expression")
    order_by: Optional[List[str]] = Field(default=[], description="List of sort expressions, e.g. ['-trxchannel_amount_sum_metric']")
    limit: Optional[int] = Field(default=None, description="Optional limit count, e.g. 10")
    partition_by: Optional[List[str]] = Field(default=[], description="Dimensions to PARTITION BY")
    max_rank: Optional[int] = Field(default=None, description="Filter for Top N per partition")


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


def ensure_manifest_ready(force: bool = False):
    """Parses project to build a native Postgres semantic manifest."""
    needs_parse = force
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


def cache_and_monkeypatch_cli():
    """
    Loads the MetricFlow Engine into RAM once, then monkeypatches the CLI configuration 
    class so that all subsequent CLI calls instantly return this pre-warmed instance.
    """
    global _CACHE_WARMED, _LAST_YAML_MTIME

    current_mtime = SCHEMA_YAML_PATH.stat().st_mtime if SCHEMA_YAML_PATH.exists() else 0

    if not _CACHE_WARMED or current_mtime > _LAST_YAML_MTIME:
        ensure_compiler_profile()
        ensure_metricflow_dummy_adapter()
        ensure_manifest_ready()

        print("⚡ Warming up MetricFlow Engine into RAM...")
        old_cwd = os.getcwd()
        try:
            os.chdir(str(DBT_PROJECT_DIR))
            os.environ["DBT_PROFILES_DIR"] = str(DBT_PROFILES_DIR)
            
            import dbt_metricflow.cli.cli_configuration as cli_config_mod

            # Dynamically locate the configuration class
            config_cls = (
                getattr(cli_config_mod, "dbtMetricFlowCliConfiguration", None)
                or getattr(cli_config_mod, "MetricFlowCliConfiguration", None)
                or getattr(cli_config_mod, "CliConfiguration", None)
                or getattr(cli_config_mod, "dbtCliConfiguration", None)
            )

            if config_cls is None:
                for attr in dir(cli_config_mod):
                    item = getattr(cli_config_mod, attr)
                    if isinstance(item, type) and hasattr(item, "mf"):
                        config_cls = item
                        break

            if config_cls is None:
                raise ImportError("Could not find configuration class inside dbt_metricflow.cli.cli_configuration")

            # Save the real __new__/__init__ on first run so both can be restored on a rebuild.
            # Restoring only __new__ (and leaving __init__ as the no-op lambda) would make
            # config_cls() skip __init__ and leave the instance without `_mf`.
            if not hasattr(config_cls, "_original_new"):
                config_cls._original_new = config_cls.__new__
            if not hasattr(config_cls, "_original_init"):
                config_cls._original_init = config_cls.__init__

            # Restore both so config_cls() runs the real __new__ AND __init__ every time.
            config_cls.__new__ = config_cls._original_new
            config_cls.__init__ = config_cls._original_init

            # 1. Instantiate configuration object
            cfg = config_cls()
            
            # 2. Run setup logic ONCE
            if hasattr(cfg, "setup"):
                cfg.setup()
                cfg.setup = lambda *args, **kwargs: None
            
            # Trigger engine graph build
            _ = cfg.mf 
            
            # 3. Monkeypatch Python to return this instance on future calls
            _original_new = config_cls.__new__
            def _cached_new(cls, *args, **kwargs):
                return cfg
            
            config_cls._original_new = _original_new
            config_cls.__new__ = staticmethod(_cached_new)
            config_cls.__init__ = lambda self, *args, **kwargs: None
            
            _CACHE_WARMED = True
            _LAST_YAML_MTIME = current_mtime
            print("✅ MetricFlow CLI successfully cached in memory!")
        finally:
            os.chdir(old_cwd)


def load_dbt_catalog() -> Dict[str, Any]:
    """Loads and parses the dbt bni_dbt_schema.yaml file."""
    if not SCHEMA_YAML_PATH.exists():
        return {"semantic_models": [], "metrics": []}
    
    with open(SCHEMA_YAML_PATH, "r") as f:
        return yaml.safe_load(f)


@app.on_event("startup")
def startup_event():
    """Bootstraps environment, forces dbt parse, and patches the CLI Engine into RAM on startup."""
    print("🚀 Bootstrapping in-memory dbt environment...")
    os.environ["DBT_PROFILES_DIR"] = str(DBT_PROFILES_DIR)
    try:
        ensure_manifest_ready(force=True)  # Forces dbt parse on every service restart
        cache_and_monkeypatch_cli()  # ensure_compiler_profile/adapter/manifest handled inside
    except Exception as e:
        print(f"⚠️ Pre-load warning on startup: {str(e)}")


@app.get("/healthz")
def health_check():
    return {"status": "healthy", "service": "dbt_service", "dbt_project_found": DBT_PROJECT_DIR.exists()}


@app.get("/api/v1/meta")
def get_semantic_catalog(query: str = None):
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
    available_entities = [] # 👈 1. Add entities list
    
    for model in catalog.get("semantic_models", []):
        model_name = model.get("name")
        
        # Extract Dimensions
        for dim in model.get("dimensions", []):
            available_dimensions.append({
                "name": f"{model_name}__{dim.get('name')}",
                "description": dim.get("description", ""),
                "meta": dim.get("meta", {})
            })
            
        # 2. Extract Entities (primary, foreign, etc.)
        for entity in model.get("entities", []):
            available_entities.append({
                "name": entity.get("name"),
                "type": entity.get("type"), # 'primary', 'foreign', etc.
                "semantic_model": model_name,
                "expr": entity.get("expr")
            })

    # Apply text filter if query parameter is passed
    if query:
        search_terms = query.lower().split()
        
        def is_match(item):
            text_to_search = f"{item.get('name', '')} {item.get('description', '')} {item.get('label', '')}".lower()
            return any(term in text_to_search for term in search_terms)

        available_metrics = [m for m in available_metrics if is_match(m)]
        available_dimensions = [d for d in available_dimensions if is_match(d)]
        available_entities = [e for e in available_entities if is_match(e)]

    # 3. Include "entities" in the JSON response
    return {
        "metrics": available_metrics, 
        "dimensions": available_dimensions,
        "entities": available_entities
    }


@app.post("/api/v1/load", response_model=MetricQueryResponse)
def execute_metric_query(payload: MetricQueryRequest):
    """Compiles dynamic MetricFlow metrics using official CLI (Monkeypatched to run in ~30ms)."""
    try:
        cache_and_monkeypatch_cli()
        
        args = ["query", "--metrics", ",".join(payload.metrics)]
        if payload.group_by:
            args.extend(["--group-by", ",".join(payload.group_by)])
        if payload.where:
            args.extend(["--where", payload.where])
            
        # If doing a PARTITIONED rank, DO NOT pass global order/limit to MetricFlow.
        # We need all rows from MetricFlow so we can rank them in the CTE wrapper.
        if not payload.partition_by:
            if payload.order_by:
                args.extend(["--order", ",".join(payload.order_by)])
            if payload.limit is not None:
                args.extend(["--limit", str(payload.limit)])
            
        args.append("--explain")

        with _MF_LOCK:
            old_cwd = os.getcwd()
            try:
                os.chdir(str(DBT_PROJECT_DIR))
                
                import dbt_metricflow.cli.main as cli_main_mod
                from click.testing import CliRunner
                import click

                main_entry = (
                    getattr(cli_main_mod, "cli", None)
                    or getattr(cli_main_mod, "main", None)
                    or getattr(cli_main_mod, "mf", None)
                    or getattr(cli_main_mod, "app", None)
                )

                if main_entry is None:
                    for attr in dir(cli_main_mod):
                        item = getattr(cli_main_mod, attr)
                        if isinstance(item, click.BaseCommand):
                            main_entry = item
                            break

                if main_entry is None:
                    raise ImportError("Could not locate Click entrypoint in dbt_metricflow.cli.main")

                runner = CliRunner()
                result = runner.invoke(main_entry, args)
                
                if result.exit_code != 0:
                    raise Exception(result.output or str(result.exception))
                output_text = result.output
            finally:
                os.chdir(old_cwd)

        # Extract SQL query block
        match = re.search(r'(?im)^(WITH|SELECT)\b', output_text)
        compiled_sql = output_text[match.start():] if match else output_text

        # Format Postgres SQL to Impala Syntax
        compiled_sql = compiled_sql.replace('"', '`')
        
        # Clean up dummy schema/database references
        compiled_sql = re.sub(r'`?dummy`?\.', '', compiled_sql)

        # =================================================================
        # SQL TEMPLATE LOGIC FOR DYNAMIC WINDOW RANKING
        # =================================================================
        if payload.partition_by:
            part_cols = ", ".join(payload.partition_by)
            
            if payload.order_by:
                order_list = [f"{c[1:]} DESC" if c.startswith("-") else f"{c} ASC" for c in payload.order_by]
                order_cols = ", ".join(order_list)
            else:
                order_cols = f"{payload.metrics[0]} DESC"

            clean_sql = compiled_sql.strip().rstrip(";")
            rank_threshold = payload.max_rank or 10
            
            # Safe default fallback just in case the LLM hallucinates a weird function
            win_func = payload.window_type.upper() if payload.window_type.upper() in ["DENSE_RANK", "RANK", "ROW_NUMBER"] else "DENSE_RANK"

            compiled_sql = f"""SELECT * FROM (
    SELECT 
        *,
        {win_func}() OVER (PARTITION BY {part_cols} ORDER BY {order_cols}) AS dynamic_rank
    FROM (
        {clean_sql}
    ) mf_base
) ranked_subq
WHERE dynamic_rank <= {rank_threshold}
ORDER BY {part_cols}, dynamic_rank ASC"""

        return MetricQueryResponse(
            status="success",
            sql=compiled_sql,
            data=[]
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Metric Compilation Failed: {str(e)}")