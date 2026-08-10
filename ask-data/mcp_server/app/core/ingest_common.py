"""
Shared helpers for the mcp_server metadata ingestion & reindex pipelines.

Centralizes the pieces that were previously duplicated or implemented
inconsistently across ``ingest_*`` / ``reindex_*`` modules:

  * ask-data/ root resolution + config_loader bootstrap
  * validated environment resolution for reindex entry points
  * the generic collection reset + embedding + bulk-upload routine
  * a consistent reindex header printer

Every ingestion pipeline in this package uses these helpers so the six
entry points behave identically.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import shared.config_loader as config_loader
from shared.embed_client import get_embeddings
from shared.qdrant_client import QdrantClient

# ---------------------------------------------------------------------------
# Root / environment bootstrap
# ---------------------------------------------------------------------------

# Location of this module file: ask-data/mcp_server/app/core/ingest_common.py
#   CORE_DIR          = _CORE_FILE.parent        = .../mcp_server/app/core
#   parents[1]        = .../mcp_server/app
#   parents[2]        = .../mcp_server
#   ASK_DATA_ROOT     = parents[3]               = .../ask-data
_CORE_FILE = Path(__file__).resolve()
CORE_DIR = _CORE_FILE.parent
_MCP_SERVER_DIR = _CORE_FILE.parents[2]
ASK_DATA_ROOT = _CORE_FILE.parents[3]


def bootstrap_env() -> Path:
    """
    Adds the ask-data/ root to ``sys.path`` and loads the shared .env into
    ``os.environ`` via ``config_loader``.

    Safe to call more than once; every ingest/reindex module calls this at
    import time so the behavior is identical regardless of entry point.
    """
    ask_data_root = ASK_DATA_ROOT
    if str(ask_data_root) not in sys.path:
        sys.path.insert(0, str(ask_data_root))

    # mcp_server/ must be importable so `app.core.*` resolves from any entry
    # point (reindex scripts, mcp_entry.py, etc.).
    if str(_MCP_SERVER_DIR) not in sys.path:
        sys.path.insert(0, str(_MCP_SERVER_DIR))

    try:
        config_loader.bootstrap(hint=ask_data_root)
    except Exception as e:
        print(f"⚠️ Warning: Failed to run config_loader bootstrap: {e}", flush=True)

    return ask_data_root


def resolve_data_path(relative_path: str) -> str:
    """
    Returns an absolute path under ask-data/ for a given project-relative
    path (e.g. ``"data/bni_schema_definitions.yaml"``).
    """
    return str(ASK_DATA_ROOT / relative_path)


# ---------------------------------------------------------------------------
# Generalized ingest routine
# ---------------------------------------------------------------------------


def reset_and_index(
    *,
    collection_name: str,
    documents: List[str],
    metadatas: List[Dict[str, Any]],
    vectordb_server_url: str,
    embed_rerank_url: str,
    cml_token: str,
    dataset_name: str,
) -> None:
    """
    Generate embeddings, flush + recreate the Qdrant collection, then bulk
    upload the documents. This is the single standardized reset-and-index
    routine used by all metadata ingest pipelines.
    """
    if not documents:
        print(f"⚠️ No documents provided for {dataset_name}.", flush=True)
        return

    qdrant_client = QdrantClient(base_url=vectordb_server_url, token=cml_token)

    print(
        f"🧠 Generating embeddings for {len(documents)} {dataset_name} "
        f"via {embed_rerank_url}...",
        flush=True,
    )
    embeddings, vector_dim = get_embeddings(
        documents, embed_rerank_url, cml_token, timeout=120.0
    )

    # Reset and recreate collection using the remote vector dimension
    qdrant_client.delete_collection(name=collection_name)
    qdrant_client.create_collection(name=collection_name, vector_size=vector_dim)

    ids = list(range(1, len(documents) + 1))
    qdrant_client.add_documents(
        collection_name=collection_name,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
        ids=ids,
    )
    print(
        f"✅ Successfully indexed {len(documents)} {dataset_name} into "
        f"'{collection_name}'!",
        flush=True,
    )


# ---------------------------------------------------------------------------
# Validated env resolution + header printing for reindex entry points
# ---------------------------------------------------------------------------


def resolve_reindex_config(
    *,
    collection_env_key: str,
    collection_default: str,
    require_embed_url: bool = True,
) -> Dict[str, str]:
    """
    Resolves and validates the shared env vars used by every reindex entry
    point.

    Returns a dict with keys ``vectordb_server_url``, ``embed_rerank_url``,
    ``cml_token``, and ``collection_name``. Exits with a clear error if
    required values are missing from the environment.
    """
    env = os.environ.copy()

    vectordb_server_url = env.get("VECTORDB_SERVER_URL")
    embed_rerank_url = env.get("EMBED_RERANK_URL")
    cml_token = env.get("CML_TOKEN", "")
    collection_name = env.get(collection_env_key, collection_default)

    if not vectordb_server_url:
        print(
            "❌ CRITICAL ERROR: 'VECTORDB_SERVER_URL' is missing or empty in .env!",
            flush=True,
        )
        sys.exit(1)

    if require_embed_url and not embed_rerank_url:
        print(
            "❌ CRITICAL ERROR: 'EMBED_RERANK_URL' is missing or empty in .env!",
            flush=True,
        )
        sys.exit(1)

    return {
        "vectordb_server_url": vectordb_server_url,
        "embed_rerank_url": embed_rerank_url,
        "cml_token": cml_token,
        "collection_name": collection_name,
    }


def print_reindex_header(
    *,
    title: str,
    config: Dict[str, str],
    collection_label: str = "Collection",
    extra_lines: Optional[List[Tuple[str, str]]] = None,
) -> None:
    """
    Prints the standardized header block shared by every reindex entry point.
    """
    print(f"🔄 {title}...", flush=True)
    print(f"- Qdrant server URL: {config['vectordb_server_url']}", flush=True)
    print(f"- Embed URL: {config['embed_rerank_url']}", flush=True)
    print(f"- {collection_label}: {config['collection_name']}", flush=True)
    for label, value in (extra_lines or []):
        print(f"- {label}: {value}", flush=True)
    if config.get("cml_token"):
        print("- CML Authentication: Token loaded successfully", flush=True)