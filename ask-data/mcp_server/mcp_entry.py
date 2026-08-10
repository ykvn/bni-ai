"""
CAI / CML Application entry point for the MCP Gateway Server.
"""
import os
import sys
from pathlib import Path

# Ensure ask-data/ root is importable before importing shared.*
_ASK_DATA_ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

from shared.entry_utils import (
    bootstrap_service,
    resolve_service_dir,
    ensure_dependencies,
    build_pythonpath,
    launch_uvicorn,
    wait_for_process,
    resolve_port,
)

_SERVICE_NAME = "mcp_server"
_CALLER_FILE = __file__ if "__file__" in globals() else None


def trigger_rag_auto_ingest(mcp_dir: Path, env: dict | None = None) -> None:
    """Triggers the knowledge ingestion pipeline using the remote embed-rerank microservice."""
    try:
        from app.core.ingest_cube_metadata import (
            CUBE_VALUE_MAPPINGS_JSON_PATH,
            CUBE_YAML_PATH,
            ingest_cube_catalog,
            ingest_value_mappings,
        )
        from app.core.ingest_knowledge import build_ingest_config, run_auto_ingest
        from app.core.ingest_sql_metadata import ingest_golden_queries, ingest_schema

        config = build_ingest_config(backend_dir=mcp_dir, env=env)

        # --- 1. INGEST PDF POLICY DOCUMENTS ---
        run_auto_ingest(
            docs_dir=config["docs_dir"],
            qdrant_server_url=config["qdrant_server_url"],
            embed_rerank_url=config["embed_rerank_url"],
            collection_name=config.get("collection_name", "bni_document_knowledge"),
            cml_token=config.get("cml_token"),
        )

        # --- 2. INGEST SCHEMA & GOLDEN QUERIES ---
        ask_data_root = mcp_dir.parent
        data_dir = ask_data_root / "data"

        schema_collection = env.get("SCHEMA_COLLECTION", "bni_schema_definitions")
        golden_collection = env.get("GOLDEN_COLLECTION", "bni_golden_queries")

        print("🔄 Running Schema and Golden Queries Ingestion...")
        ingest_schema(
            yaml_path=str(data_dir / "bni_schema_definitions.yaml"),
            vectordb_server_url=config["qdrant_server_url"],
            embed_rerank_url=config["embed_rerank_url"],
            collection_name=schema_collection,
            cml_token=config.get("cml_token")
        )

        ingest_golden_queries(
            json_path=str(data_dir / "bni_golden_queries.json"),
            vectordb_server_url=config["qdrant_server_url"],
            embed_rerank_url=config["embed_rerank_url"],
            collection_name=golden_collection,
            cml_token=config.get("cml_token")
        )

        # --- 3. INGEST CUBE CATALOG & VALUE MAPPINGS ---
        cube_catalog_collection = env.get("CUBE_CATALOG_COLLECTION", "bni_cube_catalog")
        cube_value_mappings_collection = env.get("CUBE_VALUE_MAPPINGS_COLLECTION", "bni_cube_value_mappings")

        print("🔄 Running Cube Catalog and Value Mappings Ingestion...")
        ingest_cube_catalog(
            yaml_path=CUBE_YAML_PATH,
            vectordb_server_url=config["qdrant_server_url"],
            embed_rerank_url=config["embed_rerank_url"],
            collection_name=cube_catalog_collection,
            cml_token=config.get("cml_token")
        )

        ingest_value_mappings(
            json_path=CUBE_VALUE_MAPPINGS_JSON_PATH,
            vectordb_server_url=config["qdrant_server_url"],
            embed_rerank_url=config["embed_rerank_url"],
            collection_name=cube_value_mappings_collection,
            cml_token=config.get("cml_token")
        )

    except Exception as e:
        print(f"⚠️ [RAG STARTUP WARNING] Bypass: {str(e)}")


def main() -> None:
    ask_data_root = bootstrap_service(_SERVICE_NAME)
    service_dir = resolve_service_dir(_SERVICE_NAME, ask_data_root, caller_file=_CALLER_FILE)

    # Ensure the service directory is importable in this process (CML runs from here)
    if str(service_dir) not in sys.path:
        sys.path.insert(0, str(service_dir))

    app_port = resolve_port(default=8092)

    env = os.environ.copy()
    env["PYTHONPATH"] = build_pythonpath(service_dir, ask_data_root, env=env)

    ensure_dependencies(service_dir, env)

    # Execute pre-flight knowledge ingestion using MCP context before starting Uvicorn
    print("🔄 Running pre-flight MCP Knowledge Ingestion checks...")
    trigger_rag_auto_ingest(service_dir, env=env)

    process = launch_uvicorn(service_dir, "app.main:app", app_port, env)
    print(f"🌐 Starting Aligned Production MCP Server via subprocess on http://127.0.0.1:{app_port}")

    wait_for_process(process, _SERVICE_NAME)


if __name__ == "__main__":
    main()