from __future__ import annotations

import sys
import os

# 🩹 ENTERPRISE LINUX RUNTIME PATCH: Force modern SQLite layers immediately
try:
    import pysqlite3  # type: ignore
    sys.modules["sqlite3"] = pysqlite3
except ImportError:
    pass

import chromadb
from urllib.parse import urlparse
from chromadb.api import ClientAPI
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from app.tools.config import settings

_client: ClientAPI | None = None


def _get_client() -> ClientAPI:
    """Singleton connection routine ensuring a single client connection."""
    global _client
    if _client is None:
        parsed_url = urlparse(settings.chroma_server_url)
        
        chroma_host = parsed_url.hostname
        chroma_port = parsed_url.port
        chroma_ssl = parsed_url.scheme == 'https'

        # If port is not explicitly in the URL, infer default based on scheme
        if chroma_port is None:
            chroma_port = 443 if chroma_ssl else 80

        print(f"ChromaClient connecting to: {chroma_host}:{chroma_port} (SSL: {chroma_ssl})")
        _client = chromadb.HttpClient(host=chroma_host, port=chroma_port, ssl=chroma_ssl)
    return _client


def _embedding_fn() -> SentenceTransformerEmbeddingFunction:
    """Initializes local embedding weights matching your verified configuration layer."""
    return SentenceTransformerEmbeddingFunction(model_name=settings.chroma_model)


def search_documents(query: str, collection_name: str, top_k: int = 5) -> list[dict]:
    """
    Queries local persistent vector stores and normalizes output arrays 
    into standardized dictionary formats with calculated similarity metrics.
    """
    client = _get_client()
    
    try:
        collection = client.get_collection(
            name=collection_name,
            embedding_function=_embedding_fn(),
        )
        results = collection.query(query_texts=[query], n_results=top_k)

        docs = results.get("documents", [[]])[0] if results.get("documents") else []
        metadatas = results.get("metadatas", [[]])[0] if results.get("metadatas") else []
        distances = results.get("distances", [[]])[0] if results.get("distances") else []

        output = []
        for doc, meta, dist in zip(docs, metadatas, distances):
            # Transform distance arrays into clean 0.0 - 1.0 Similarity Scores
            score = round(1 - dist, 4) if dist is not None else None
            
            source_file = meta.get("source_file", meta.get("source", "Unknown_Document"))
            page_num = meta.get("page", "?")
            
            output.append({
                "document_id": source_file,
                "title": f"{source_file} (halaman {page_num})",
                "excerpt": doc[:400] if doc else "",
                "score": score,
            })
        return output
        
    except Exception as e:
        print(f"⚠️ Vector search operational failure: {str(e)}")
        return [{"error": f"Vector Store Failure: {str(e)}"}]