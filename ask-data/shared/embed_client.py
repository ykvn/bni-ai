"""
Shared remote embedding and reranking client.

Consolidates the repeated HTTP calls to the embed-rerank microservice
across mcp_server tools and ingestion pipelines.
"""
from __future__ import annotations

import os
import urllib3
import requests

from shared.cml_auth import build_cml_headers

# Bypass internal CML SSL certificate warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def resolve_embed_rerank_url() -> str:
    """Resolves the embed-rerank microservice URL from environment variables."""
    return (
        os.getenv("EMBED_RERANK_URL")
        or os.getenv("SEMANTIC_ENGINE_URL")
        or "http://127.0.0.1:8090"
    ).rstrip("/")


def get_embeddings(
    texts: str | list[str],
    engine_url: str | None = None,
    cml_token: str | None = None,
    timeout: float = 30.0,
) -> tuple[list[list[float]], int]:
    """
    Fetches vector embeddings for a query string or list of strings from
    the remote embed-rerank microservice.

    Returns a tuple of (embeddings, dimension).
    """
    engine_url = (engine_url or resolve_embed_rerank_url()).rstrip("/")
    headers = build_cml_headers(cml_token, {"Content-Type": "application/json"})

    res = requests.post(
        f"{engine_url}/v1/embeddings",
        json={"input": texts},
        headers=headers,
        verify=False,
        timeout=timeout,
    )
    res.raise_for_status()
    payload = res.json()
    return payload["embeddings"], payload.get("dimension", 0)


def get_embedding_vector(
    query: str,
    engine_url: str | None = None,
    cml_token: str | None = None,
    timeout: float = 30.0,
) -> list[float]:
    """
    Fetches a single embedding vector for a query string.
    Handles both list and single-vector response formats.
    """
    embeddings, _ = get_embeddings(query, engine_url, cml_token, timeout)
    if embeddings and isinstance(embeddings[0], list):
        return embeddings[0]
    return embeddings


def rerank_documents(
    query: str,
    documents: list[str],
    engine_url: str | None = None,
    cml_token: str | None = None,
    top_n: int = 5,
    timeout: float = 30.0,
) -> list[dict]:
    """
    Reranks candidate document snippets remotely via the embed-rerank
    Cross-Encoder microservice.

    Returns a list of dicts with 'index' and 'score' keys.
    """
    if not documents:
        return []

    engine_url = (engine_url or resolve_embed_rerank_url()).rstrip("/")
    headers = build_cml_headers(cml_token, {"Content-Type": "application/json"})

    res = requests.post(
        f"{engine_url}/v1/rerank",
        json={"query": query, "documents": documents, "top_n": top_n},
        headers=headers,
        verify=False,
        timeout=timeout,
    )
    res.raise_for_status()
    data = res.json()

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("results", data.get("data", []))
    return []