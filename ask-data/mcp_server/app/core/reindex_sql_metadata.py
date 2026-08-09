"""
Re-index entry point for SQL metadata (schema + golden queries).

Uses the shared ``ingest_common`` bootstrap, env resolution, and header
printer so behavior is identical to the Cube and knowledge reindexers.
"""
from app.core.ingest_common import (
    bootstrap_env,
    print_reindex_header,
    resolve_data_path,
    resolve_reindex_config,
)
from app.core.ingest_sql_metadata import ingest_golden_queries, ingest_schema

# Standardized project-root bootstrap (idempotent, shared across all pipelines)
bootstrap_env()

# --- PATH CONFIGURATION ---
SCHEMA_YAML_PATH = resolve_data_path("data/bni_schema_definitions.yaml")
GOLDEN_QUERIES_JSON_PATH = resolve_data_path("data/bni_golden_queries.json")


def main() -> None:
    # Validated shared env resolution (exits with a clear error if missing)
    schema_config = resolve_reindex_config(
        collection_env_key="SCHEMA_COLLECTION",
        collection_default="sql_schema",
    )
    golden_config = resolve_reindex_config(
        collection_env_key="GOLDEN_COLLECTION",
        collection_default="golden_queries",
    )

    print_reindex_header(
        title="Re-indexing SQL Metadata",
        config=schema_config,
        collection_label="Schema Collection",
        extra_lines=[("Golden Queries Collection", golden_config["collection_name"])],
    )

    # 1. Index the traditional SQL Schema
    print(f"\n[1/2] Indexing Database Schema from {SCHEMA_YAML_PATH}...", flush=True)
    ingest_schema(
        yaml_path=SCHEMA_YAML_PATH,
        vectordb_server_url=schema_config["vectordb_server_url"],
        embed_rerank_url=schema_config["embed_rerank_url"],
        collection_name=schema_config["collection_name"],
        cml_token=schema_config["cml_token"],
    )

    # 2. Index the Golden Queries
    print(f"\n[2/2] Indexing Golden Queries from {GOLDEN_QUERIES_JSON_PATH}...", flush=True)
    ingest_golden_queries(
        json_path=GOLDEN_QUERIES_JSON_PATH,
        vectordb_server_url=golden_config["vectordb_server_url"],
        embed_rerank_url=golden_config["embed_rerank_url"],
        collection_name=golden_config["collection_name"],
        cml_token=golden_config["cml_token"],
    )

    print("\n🎉 SQL metadata re-indexing completed successfully!", flush=True)


if __name__ == "__main__":
    main()