"""
Re-index entry point for MetricFlow Catalog.

Uses the shared ``ingest_common`` bootstrap, env resolution, and header printer
"""
import sys
from pathlib import Path

# --- sys.path bootstrap ---
_ASK_DATA_ROOT = Path(__file__).resolve().parents[3] if "__file__" in globals() else Path("/home/cdsw/ask-data")
_MCP_SERVER_DIR = _ASK_DATA_ROOT / "mcp_server"
for _p in (str(_ASK_DATA_ROOT), str(_MCP_SERVER_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.core.ingest_common import (
    bootstrap_env,
    print_reindex_header,
    resolve_data_path,
    resolve_reindex_config,
)
from app.core.ingest_mf_metadata import ingest_mf_schema

# Standardized project-root bootstrap
bootstrap_env()

# --- PATH CONFIGURATION ---
MF_SCHEMA_YAML_PATH = resolve_data_path("dbt_service/dbt_project/models/bni_dbt_schema.yaml")

def main() -> None:
    # Validated shared env resolution
    config = resolve_reindex_config(
        collection_env_key="MF_CATALOG_COLLECTION",
        collection_default="mf_catalog",
    )

    print_reindex_header(
        title="Re-indexing MetricFlow Catalog",
        config=config,
        collection_label="MF Catalog Collection",
    )

    print(f"\n[1/1] Indexing MetricFlow Schema from {MF_SCHEMA_YAML_PATH}...", flush=True)
    ingest_mf_schema(
        yaml_path=MF_SCHEMA_YAML_PATH,
        vectordb_server_url=config["vectordb_server_url"],
        embed_rerank_url=config["embed_rerank_url"],
        collection_name=config["collection_name"],
        cml_token=config["cml_token"],
    )

    print("\n🎉 MetricFlow metadata re-indexing completed successfully!", flush=True)

if __name__ == "__main__":
    main()