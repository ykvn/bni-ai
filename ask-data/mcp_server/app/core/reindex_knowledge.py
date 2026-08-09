"""
Re-index entry point for the knowledge base (PDF documents).

Uses the shared ``ingest_common`` bootstrap, env resolution, and header
printer so behavior is identical to the SQL and Cube reindexers.
"""
from pathlib import Path

from app.core.ingest_common import (
    bootstrap_env,
    print_reindex_header,
    resolve_reindex_config,
)
from app.core.ingest_knowledge import build_ingest_config, run_auto_ingest

# Standardized project-root bootstrap (idempotent, shared across all pipelines)
bootstrap_env()


def main() -> None:
    # Validated shared env resolution (exits with a clear error if missing)
    config = resolve_reindex_config(
        collection_env_key="DOCUMENT_COLLECTION",
        collection_default="documents",
    )

    # Resolve the docs directory (falls back to ask-data/data/documents)
    # Pass the mcp_server/ directory so the relative fallback lands on
    # ask-data/data/documents.
    backend_dir = Path(__file__).resolve().parents[2]
    ingest_config = build_ingest_config(backend_dir=backend_dir, env=None)
    docs_dir = ingest_config["docs_dir"]

    print_reindex_header(
        title="Re-indexing knowledge base",
        config=config,
        collection_label="Collection",
        extra_lines=[("docs dir", docs_dir)],
    )

    run_auto_ingest(
        docs_dir=docs_dir,
        qdrant_server_url=config["vectordb_server_url"],
        embed_rerank_url=config["embed_rerank_url"],
        collection_name=config["collection_name"],
        cml_token=config["cml_token"],
    )


if __name__ == "__main__":
    main()