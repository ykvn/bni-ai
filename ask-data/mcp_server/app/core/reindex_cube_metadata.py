import os
import sys
from pathlib import Path

# 1. Locate ask-data root and bootstrap .env into os.environ BEFORE importing app modules
_ASK_DATA_ROOT = Path(__file__).resolve().parents[2] if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

try:
    import shared.config_loader as config_loader
    config_loader.bootstrap(hint=_ASK_DATA_ROOT)
except Exception as e:
    print(f"⚠️ Warning: Failed to run config_loader bootstrap: {e}", flush=True)

# Import the Cube ingestion functions and paths we created previously
from app.core.ingest_cube_metadata import (
    ingest_cube_catalog,
    ingest_value_mappings,
    CUBE_YAML_PATH,
    CUBE_VALUE_MAPPINGS_JSON_PATH
)


def main() -> None:
    # Ensure mcp_server root is in the path for internal imports
    mcp_server_dir = Path(__file__).resolve().parents[2] if "__file__" in globals() else Path.cwd()
    if str(mcp_server_dir) not in sys.path:
        sys.path.insert(0, str(mcp_server_dir))

    # Load environment variables injected by config_loader
    env = os.environ.copy()

    # Resolve URLs, supporting standard ask-data env vars as fallbacks
    vectordb_server_url = env.get("VECTORDB_SERVER_URL")
    embed_rerank_url = env.get("EMBED_RERANK_URL")
    cml_token = env.get("CML_TOKEN", "")

    # Define standard collections for Cube
    cube_catalog_collection = env.get("CUBE_CATALOG_COLLECTION", "bni_cube_catalog")
    cube_value_mappings_collection = env.get("CUBE_VALUE_MAPPINGS_COLLECTION", "bni_cube_value_mappings")

    # 2. Add validation guards to catch missing .env values early
    if not vectordb_server_url:
        print("❌ CRITICAL ERROR: 'VECTORDB_SERVER_URL' is missing or empty in .env!", flush=True)
        sys.exit(1)

    if not embed_rerank_url:
        print("❌ CRITICAL ERROR: 'EMBED_RERANK_URL' is missing or empty in .env!", flush=True)
        sys.exit(1)

    print("🔄 Re-indexing Cube Metadata...", flush=True)
    print(f"- Qdrant server URL: {vectordb_server_url}", flush=True)
    print(f"- Embed URL: {embed_rerank_url}", flush=True)
    print(f"- Catalog Collection: {cube_catalog_collection}", flush=True)
    print(f"- Value Mappings Collection: {cube_value_mappings_collection}", flush=True)

    if cml_token:
        print("- CML Authentication: Token loaded successfully", flush=True)

    # 3. Execute the Cube Semantic Model indexer
    print(f"\n[1/2] Indexing Cube Catalog from {CUBE_YAML_PATH}...", flush=True)
    ingest_cube_catalog(
        yaml_path=CUBE_YAML_PATH,
        vectordb_server_url=vectordb_server_url,
        embed_url=embed_rerank_url,
        collection_name=cube_catalog_collection,
        cml_token=cml_token
    )

    # 4. Execute the Value Mappings indexer
    print(f"\n[2/2] Indexing Value Mappings from {CUBE_VALUE_MAPPINGS_JSON_PATH}...", flush=True)
    ingest_value_mappings(
        json_path=CUBE_VALUE_MAPPINGS_JSON_PATH,
        vectordb_server_url=vectordb_server_url,
        embed_url=embed_rerank_url,
        collection_name=cube_value_mappings_collection,
        cml_token=cml_token
    )

    print("\n🎉 Cube metadata re-indexing completed successfully!", flush=True)


if __name__ == "__main__":
    main()