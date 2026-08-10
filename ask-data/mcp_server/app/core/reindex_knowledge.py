"""
Re-index entry point for the knowledge base (PDF documents).

Uses the shared ``ingest_common`` bootstrap, env resolution, and header
printer so behavior is identical to the SQL and Cube reindexers.
"""
import sys
from pathlib import Path

# --- sys.path bootstrap (must run BEFORE app.core.* imports) ---
# This file lives at ask-data/mcp_server/app/core/reindex_*.py, so:
#   parents[3] = ask-data/   (for shared.* imports)
#   parents[2] = mcp_server/ (for app.* imports)
_ASK_DATA_ROOT = Path(__file__).resolve().parents[3] if "__file__" in globals() else Path("/home/cdsw/ask-data")
_MCP_SERVER_DIR = _ASK_DATA_ROOT / "mcp_server"
for _p in (str(_ASK_DATA_ROOT), str(_MCP_SERVER_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

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