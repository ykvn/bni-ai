from __future__ import annotations

import os
import requests
import urllib3
from sentence_transformers import SentenceTransformer
from app.tools.config import settings

# Bypass internal CML SSL certificate warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_embedding_model: SentenceTransformer | None = None


def _get_embedding_model() -> SentenceTransformer:
    """Initializes local embedding weights matching your verified configuration layer."""
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(settings.qdrant_model)
    return _embedding_model


def search_documents(query: str, collection_name: str, top_k: int = 5) -> list[dict]:
    """
    Queries Qdrant vector stores via native REST API and normalizes output arrays 
    into standardized dictionary formats with calculated similarity metrics.
    """
    qdrant_url = settings.qdrant_server_url.rstrip("/")
    cml_token = (
        os.getenv("CML_TOKEN") 
        or os.getenv("CDSW_API_KEY") 
        or os.getenv("QDRANT_SERVER_TOKEN") 
        or ""
    ).strip()
    
    try:
        # 1. Generate the query embedding
        embedder = _get_embedding_model()
        query_vector = embedder.encode(query).tolist()

        # 2. Prepare the Qdrant REST API Request
        search_url = f"{qdrant_url}/collections/{collection_name}/points/search"
        
        # Force the exact Authorization header required by CML Ingress Proxies
        headers = {}
        if cml_token:
            headers["Authorization"] = f"Bearer {cml_token}"

        payload = {
            "vector": query_vector,
            "limit": top_k,
            "with_payload": True
        }

        # 3. Execute request with an explicit 60-second timeout to prevent proxy drops
        res = requests.post(
            search_url, 
            json=payload, 
            headers=headers, 
            verify=False, 
            timeout=60.0
        )
        
        if res.status_code != 200:
            return [{"error": f"Qdrant HTTP Error {res.status_code}: {res.text}"}]

        # 4. Parse the REST response payload
        results = res.json().get("result", [])
        output = []
        
        for item in results:
            payload_data = item.get("payload", {})
            score = round(float(item.get("score", 0.0)), 4) if item.get("score") is not None else None
            
            source_file = payload_data.get("source_file", payload_data.get("title", "Unknown_Document"))
            page_num = payload_data.get("page", "?")
            doc_text = payload_data.get("page_content", payload_data.get("excerpt", ""))
            
            output.append({
                "document_id": str(item.get("id", "unknown")),
                "title": f"{source_file} (halaman {page_num})" if page_num != "?" else source_file,
                "excerpt": doc_text[:400] if doc_text else "",
                "score": score,
            })
            
        return output
        
    except Exception as e:
        print(f"⚠️ Vector search operational failure: {str(e)}")
        return [{"error": f"Vector Store Failure: {str(e)}"}]