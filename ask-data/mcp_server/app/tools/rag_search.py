import os
import urllib3
import requests
from pathlib import Path
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

# Load .env file explicitly
_mcp_env_path = Path(__file__).resolve().parents[2] / ".env"
if _mcp_env_path.exists():
    load_dotenv(_mcp_env_path, override=True)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_embedding_model = None

def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedding_model


def perform_rag_search(query: str, n_results: int = 3) -> str:
    normalized_query = query.strip()
    if not normalized_query:
        return "Search Context: Empty query provided."

    chroma_url = os.environ.get("CHROMA_SERVER_URL", "").rstrip("/")
    collection_name = os.environ.get("CHROMA_COLLECTION", "bank_abc_knowledge")
    
    cml_token = (
        os.environ.get("CML_TOKEN") 
        or os.environ.get("CDSW_API_KEY") 
        or os.environ.get("CHROMA_SERVER_TOKEN") 
        or ""
    ).strip()

    if not chroma_url:
        return "⚠️ [MCP Error] CHROMA_SERVER_URL environment variable is not configured."

    session = requests.Session()
    session.verify = False
    
    if cml_token:
        session.headers.update({"Authorization": f"Bearer {cml_token}"})

    try:
        get_coll_url = f"{chroma_url}/api/v1/collections/{collection_name}"
        res = session.get(get_coll_url, timeout=15, allow_redirects=False)

        if res.status_code in (301, 302, 401, 403):
            return f"⚠️ [MCP Auth Error] CML Gateway redirected request to Login (Status {res.status_code})."

        if res.status_code != 200:
            return f"Search Context for '{query}': Collection '{collection_name}' not found in ChromaDB."

        collection_id = res.json()["id"]

        model = _get_embedding_model()
        query_vector = model.encode([normalized_query]).tolist()

        query_url = f"{chroma_url}/api/v1/collections/{collection_id}/query"
        payload = {
            "query_embeddings": query_vector,
            "n_results": n_results,
            "include": ["documents", "metadatas"]
        }
        
        query_res = session.post(query_url, json=payload, timeout=30, allow_redirects=False)

        if query_res.status_code in (301, 302, 401, 403):
            return f"⚠️ [MCP Auth Error] Vector query endpoint returned HTTP {query_res.status_code} Auth Redirect."

        query_res.raise_for_status()
        data = query_res.json()

        documents = data.get("documents", [[]])[0]
        if not documents:
            return f"Search Context for '{query}': No matching vector nodes found in knowledge base."

        return "\n\n---\n\n".join(documents)

    except Exception as err:
        return f"⚠️ [MCP RAG Error] Could not query ChromaDB endpoint: {str(err)}"