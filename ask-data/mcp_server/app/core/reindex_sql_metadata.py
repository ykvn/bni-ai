import os
import sys
from pathlib import Path

# 1. Locate ask-data root and bootstrap .env into os.environ BEFORE importing app modules[cite: 17, 18]
_ASK_DATA_ROOT = Path(__file__).resolve().parents[2] if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

try:
    import shared.config_loader as config_loader
    config_loader.bootstrap(hint=_ASK_DATA_ROOT)
except Exception as e:
    print(f"⚠️ Warning: Failed to run config_loader bootstrap: {e}", flush=True)

# Import the SQL ingestion functions[cite: 18]
from app.core.ingest_sql_metadata import ingest_golden_queries, ingest_schema

# --- PATH CONFIGURATION ---
SCHEMA_YAML_PATH = os.path.join(_ASK_DATA_ROOT, "data", "schema_definitions.yaml")
GOLDEN_QUERIES_JSON_PATH = os.path.join(_ASK_DATA_ROOT, "data", "golden_queries.json")


def main() -> None:
    # Ensure mcp_server root is in the path for internal imports[cite: 17]
    mcp_server_dir = Path(__file__).resolve().parents[2] if "__file__" in globals() else Path.cwd()
    if str(mcp_server_dir) not in sys.path:
        sys.path.insert(0, str(mcp_server_dir))

    # Load environment variables injected by config_loader[cite: 17]
    env = os.environ.copy()

    # Resolve URLs, supporting standard ask-data env vars as fallbacks
    vectordb_server_url = env.get("VECTORDB_SERVER_URL")
    embed_rerank_url = env.get("EMBED_RERANK_URL")
    cml_token = env.get("CML_TOKEN", "")

    # Define standard collections for traditional SQL RAG
    sql_schema_collection = env.get("SCHEMA_COLLECTION", "sql_schema")
    golden_queries_collection = env.get("GOLDEN_COLLECTION", "golden_queries")

    # 2. Add validation guards to catch missing .env values early[cite: 17]
    if not vectordb_server_url:
        print("❌ CRITICAL ERROR: 'VECTORDB_SERVER_URL' is missing or empty in .env!", flush=True)
        sys.exit(1)

    if not embed_rerank_url:
        print("❌ CRITICAL ERROR: 'EMBED_RERANK_URL' is missing or empty in .env!", flush=True)
        sys.exit(1)

    print("🔄 Re-indexing SQL Metadata...", flush=True)
    print(f"- Qdrant server URL: {vectordb_server_url}", flush=True)
    print(f"- Embed URL: {embed_rerank_url}", flush=True)
    print(f"- Schema Collection: {sql_schema_collection}", flush=True)
    print(f"- Golden Queries Collection: {golden_queries_collection}", flush=True)
    
    if cml_token:
        print("- CML Authentication: Token loaded successfully", flush=True)

    # 3. Execute the traditional SQL Schema indexer[cite: 18]
    print(f"\n[1/2] Indexing Database Schema from {SCHEMA_YAML_PATH}...", flush=True)
    ingest_schema(
        yaml_path=SCHEMA_YAML_PATH,
        qdrant_url=vectordb_server_url,
        embed_url=embed_rerank_url,
        collection_name=sql_schema_collection,
        cml_token=cml_token
    )

    # 4. Execute the Golden Queries indexer[cite: 18]
    print(f"\n[2/2] Indexing Golden Queries from {GOLDEN_QUERIES_JSON_PATH}...", flush=True)
    ingest_golden_queries(
        json_path=GOLDEN_QUERIES_JSON_PATH,
        qdrant_url=vectordb_server_url,
        embed_url=embed_rerank_url,
        collection_name=golden_queries_collection,
        cml_token=cml_token
    )

    print("\n🎉 SQL metadata re-indexing completed successfully!", flush=True)


if __name__ == "__main__":
    main()