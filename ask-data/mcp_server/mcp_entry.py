import os
import sys
import subprocess
from pathlib import Path

# 1. Global config: load the single ask-data/.env BEFORE any service code reads env vars.
_ASK_DATA_ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

import shared.config_loader as config_loader
config_loader.bootstrap(hint=_ASK_DATA_ROOT)


def resolve_mcp_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    return _ASK_DATA_ROOT / "mcp_server"

MCP_DIR = resolve_mcp_dir()
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))

from app.core.ingest_knowledge import build_ingest_config, run_auto_ingest
from app.core.ingest_sql_metadata import ingest_golden_queries, ingest_schema

def ensure_dependencies(mcp_dir: Path, env: dict) -> None:
    """
    Validates and installs packages from requirements.txt directly 
    into the CML application container runtime environment.
    """
    req_file = mcp_dir / "requirements.txt"
    if not req_file.exists():
        print(f"⚠️ No requirements.txt found at {req_file}. Skipping dependency installation.")
        return
        
    print(f"📦 Validating dependencies from {req_file}...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"],
            check=True,
            env=env,
        )
        print("✅ Dependencies verified successfully.")
    except subprocess.CalledProcessError as e:
        print(f"❌ Critical Error: Failed to configure dependencies: {str(e)}")
        sys.exit(1)


def trigger_rag_auto_ingest(mcp_dir: Path, env: dict | None = None) -> None:
    """Triggers the knowledge ingestion pipeline using the remote embed-rerank microservice."""
    try:
        config = build_ingest_config(backend_dir=mcp_dir, env=env)
        
        # --- 1. INGEST PDF POLICY DOCUMENTS ---
        run_auto_ingest(
            docs_dir=config["docs_dir"],
            qdrant_server_url=config["qdrant_server_url"],
            embed_rerank_url=config["embed_rerank_url"],
            qdrant_ssl=config["qdrant_ssl"],
            collection_name=config.get("collection_name", "bni_document_knowledge"),
            cml_token=config.get("cml_token"),
        )
        
        # --- 2. INGEST SCHEMA & GOLDEN QUERIES ---
        data_dir = _ASK_DATA_ROOT / "data" 
        
        schema_collection = env.get("SCHEMA_COLLECTION", "bni_schema_definitions")
        golden_collection = env.get("GOLDEN_COLLECTION", "bni_golden_queries")
        
        print("🔄 Running Schema and Golden Queries Ingestion...")
        ingest_schema(
            yaml_path=str(data_dir / "domain_config.yaml"),
            qdrant_url=config["qdrant_server_url"],
            embed_url=config["embed_rerank_url"],
            collection_name=schema_collection,
            cml_token=config.get("cml_token")
        )
        
        ingest_golden_queries(
            json_path=str(data_dir / "golden_queries.json"),
            qdrant_url=config["qdrant_server_url"],
            embed_url=config["embed_rerank_url"],
            collection_name=golden_collection,
            cml_token=config.get("cml_token")
        )
        
    except Exception as e:
        print(f"⚠️ [RAG STARTUP WARNING] Bypass: {str(e)}")


def main() -> None:
    os.chdir(MCP_DIR)
    
    # Extract the dynamically allocated port by the CML environment
    app_port = int(os.environ.get("CDSW_APP_PORT"))
    
    # Patch environment variables with absolute PYTHONPATH injections
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{MCP_DIR}:{pythonpath}" if pythonpath else str(MCP_DIR)
    
    # Handle dependency resolution before thread initialization
    ensure_dependencies(MCP_DIR, env)
    
    # Execute pre-flight knowledge ingestion using MCP context before starting Uvicorn
    print("🔄 Running pre-flight MCP Knowledge Ingestion checks...")
    trigger_rag_auto_ingest(MCP_DIR, env=env)
    
    # Standardized operational startup parameter array targeting app.main:app
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",       
        "--host",
        "127.0.0.1",
        "--port",
        str(app_port),
        "--log-level",
        "warning"
    ]
    
    print(f"🌐 Starting Aligned Production MCP Server via subprocess on http://127.0.0.1:{app_port}")
    print(f"📍 Resolved Execution Root Context: {MCP_DIR}")
    
    # Launch Uvicorn cleanly inside its own isolated operating system process
    process = subprocess.Popen(cmd, cwd=str(MCP_DIR), env=env)
    
    try:
        process.wait()
    except KeyboardInterrupt:
        print("\n🛑 Gateway loop execution interrupted. Purging active proxy sockets...")
        process.terminate()

if __name__ == "__main__":
    main()