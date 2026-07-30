import os
import urllib3
import requests
from sentence_transformers import SentenceTransformer

# Suppress SSL warnings for internal CML certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Lazily load embedding model to save memory during cold starts
_embedding_model = None

def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedding_model


def perform_rag_search(query: str, n_results: int = 3) -> str:
    """
    Queries the standalone ChromaDB HTTP application endpoint 
    for relevant knowledge base context using CML Bearer authentication.
    """
    normalized_query = query.strip()
    if not normalized_query:
        return "Search Context: Empty query provided."

    chroma_url = os.environ.get("CHROMA_SERVER_URL", "http://localhost:8000").rstrip("/")
    collection_name = os.environ.get("CHROMA_COLLECTION", "bank_abc_knowledge")
    cml_token = os.environ.get("CML_TOKEN", "").strip()

    headers = {}
    if cml_token:
        headers["Authorization"] = f"Bearer {cml_token}"

    session = requests.Session()
    session.verify = False  # Handles internal CML self-signed SSL certificates
    session.headers.update(headers)

    try:
        # 1. Resolve Collection ID from ChromaDB REST API
        get_coll_url = f"{chroma_url}/api/v1/collections/{collection_name}"
        res = session.get(get_coll_url, timeout=15)
        
        if res.status_code != 200:
            return f"Search Context for '{query}': Collection '{collection_name}' not found in ChromaDB."

        collection_id = res.json()["id"]

        # 2. Embed the search query
        model = _get_embedding_model()
        query_vector = model.encode([normalized_query]).tolist()

        # 3. Perform Vector Similarity Search
        query_url = f"{chroma_url}/api/v1/collections/{collection_id}/query"
        payload = {
            "query_embeddings": query_vector,
            "n_results": n_results,
            "include": ["documents", "metadatas"]
        }
        
        query_res = session.post(query_url, json=payload, timeout=30)
        query_res.raise_for_status()
        data = query_res.json()

        # 4. Extract retrieved document fragments
        documents = data.get("documents", [[]])[0]
        if not documents:
            return f"Search Context for '{query}': No matching vector nodes found in knowledge base."

        return "\n\n---\n\n".join(documents)

    except Exception as err:
        return f"⚠️ [MCP RAG Error] Could not query ChromaDB endpoint: {str(err)}"