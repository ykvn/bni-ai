"""
Re-index entry point for Cube metadata (catalog + value mappings).

Uses the shared ``ingest_common`` bootstrap, env resolution, and header
printer so behavior is identical to the SQL and knowledge reindexers.
"""
from app.core.ingest_common import (
    bootstrap_env,
    print_reindex_header,
    resolve_data_path,
    resolve_reindex_config,
)
from app.core.ingest_cube_metadata import (
    CUBE_VALUE_MAPPINGS_JSON_PATH,
    CUBE_YAML_PATH,
    ingest_cube_catalog,
    ingest_value_mappings,
)

# Standardized project-root bootstrap (idempotent, shared across all pipelines)
bootstrap_env()


def main() -> None:
    # Validated shared env resolution (exits with a clear error if missing)
    catalog_config = resolve_reindex_config(
        collection_env_key="CUBE_CATALOG_COLLECTION",
        collection_default="bni_cube_catalog",
    )
    mappings_config = resolve_reindex_config(
        collection_env_key="CUBE_VALUE_MAPPINGS_COLLECTION",
        collection_default="bni_cube_value_mappings",
    )

    print_reindex_header(
        title="Re-indexing Cube Metadata",
        config=catalog_config,
        collection_label="Catalog Collection",
        extra_lines=[("Value Mappings Collection", mappings_config["collection_name"])],
    )

    # 1. Index the Cube Semantic Model
    print(f"\n[1/2] Indexing Cube Catalog from {CUBE_YAML_PATH}...", flush=True)
    ingest_cube_catalog(
        yaml_path=CUBE_YAML_PATH,
        vectordb_server_url=catalog_config["vectordb_server_url"],
        embed_rerank_url=catalog_config["embed_rerank_url"],
        collection_name=catalog_config["collection_name"],
        cml_token=catalog_config["cml_token"],
    )

    # 2. Index the Value Mappings
    print(
        f"\n[2/2] Indexing Value Mappings from {CUBE_VALUE_MAPPINGS_JSON_PATH}...",
        flush=True,
    )
    ingest_value_mappings(
        json_path=CUBE_VALUE_MAPPINGS_JSON_PATH,
        vectordb_server_url=mappings_config["vectordb_server_url"],
        embed_rerank_url=mappings_config["embed_rerank_url"],
        collection_name=mappings_config["collection_name"],
        cml_token=mappings_config["cml_token"],
    )

    print("\n🎉 Cube metadata re-indexing completed successfully!", flush=True)


if __name__ == "__main__":
    main()