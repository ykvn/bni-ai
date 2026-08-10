"""
Shared Qdrant vector store client.

Consolidates the repeated Qdrant HTTP operations (search, collection
management, bulk document upload) across mcp_server tools and
ingestion pipelines.
"""
from __future__ import annotations

import time
import urllib3
import requests

from shared.cml_auth import build_cml_headers

# Bypass internal CML SSL certificate warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class QdrantClient:
    """
    A lightweight Qdrant REST Client built on Python 'requests'.
    Uses CML Bearer authentication, SSL bypass, and extended gateway timeouts.
    """

    def __init__(self, base_url: str, token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.verify = False  # Bypasses internal CML SSL certificate issues

        if token:
            # Send both Bearer token (CML) and api-key (Qdrant) authentication
            self.session.headers.update(build_cml_headers(token))
            self.session.headers["api-key"] = token
        else:
            print("⚠️ Notice: No CML token loaded. Request may fail if CML Application authentication is enabled.", flush=True)

        self._warmup_gateway()

    def _warmup_gateway(self) -> None:
        """Pings Qdrant health endpoint to warm up CML OAuth Proxy session."""
        url = f"{self.base_url}/collections"
        for attempt in range(1, 4):
            try:
                res = self.session.get(url, timeout=120)
                if res.status_code == 200:
                    print("⚡ CML Gateway proxy connection established successfully.", flush=True)
                    return
            except Exception:
                time.sleep(2)

    def delete_collection(self, name: str) -> None:
        """Deletes an existing collection if present."""
        url = f"{self.base_url}/collections/{name}"
        try:
            res = self.session.delete(url, timeout=120)
            if res.status_code == 200:
                print(f"🧹 [RAG ENGINE] Flushed old vector collection cache: '{name}'", flush=True)
            else:
                print(f"ℹ️ [RAG ENGINE] Collection reset notice (Status {res.status_code})", flush=True)
        except Exception as e:
            print(f"ℹ️ [RAG ENGINE] Notice during collection reset: {e}", flush=True)

    def create_collection(self, name: str, vector_size: int) -> None:
        """Creates a new collection in Qdrant configured for vector embeddings."""
        url = f"{self.base_url}/collections/{name}"
        payload = {
            "vectors": {
                "size": vector_size,
                "distance": "Cosine"
            }
        }
        res = self.session.put(url, json=payload, timeout=120)
        res.raise_for_status()

    def add_documents(
        self,
        collection_name: str,
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
        ids: list[int],
        batch_size: int = 100,
    ) -> None:
        """Pushes text fragments and vector embeddings to Qdrant in safe batches."""
        url = f"{self.base_url}/collections/{collection_name}/points?wait=true"

        all_points = []
        for point_id, doc, emb, meta in zip(ids, documents, embeddings, metadatas):
            payload = {**meta, "page_content": doc}
            all_points.append({
                "id": point_id,
                "vector": emb,
                "payload": payload
            })

        # Batch upload points to prevent HTTP 413 / Gateway Timeout errors
        for i in range(0, len(all_points), batch_size):
            batch = all_points[i:i + batch_size]
            request_body = {"points": batch}
            res = self.session.put(url, json=request_body, timeout=120)
            res.raise_for_status()

    def get_count(self, collection_name: str) -> int:
        """Returns active vector count in collection."""
        url = f"{self.base_url}/collections/{collection_name}/points/count"
        try:
            res = self.session.post(url, json={"exact": True}, timeout=120)
            if res.status_code == 200:
                return res.json().get("result", {}).get("count", 0)
        except Exception:
            pass
        return 0

    def search(
        self,
        collection_name: str,
        query_vector: list[float],
        top_k: int = 5,
        token: str | None = None,
    ) -> list[dict]:
        """
        Searches for the most similar points in a Qdrant collection.

        Returns a list of point dicts, each with 'id', 'score', and 'payload'.
        """
        search_url = f"{self.base_url}/collections/{collection_name}/points/search"

        headers = {}
        if token:
            headers = build_cml_headers(token)
            headers["api-key"] = token

        payload = {
            "vector": query_vector,
            "limit": top_k,
            "with_payload": True
        }

        res = requests.post(
            search_url,
            json=payload,
            headers=headers,
            verify=False,
            timeout=60.0,
        )

        if res.status_code != 200:
            return [{"error": f"Qdrant HTTP Error {res.status_code}: {res.text}"}]

        return res.json().get("result", [])