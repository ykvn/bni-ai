import os
import urllib3
import requests
from pathlib import Path
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

# 1. Force load the exact same .env file the backend uses
_mcp_env_path = Path(__file__).resolve().parents[2] / ".env"
if _mcp_env_path.exists():
    load_dotenv(_mcp_env_path, override=True)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
_embedding_model = None

# If you use CrewAI, keep your @tool decorator here!
def search_policy_documents(query: str, n_results: int = 3) -> str:
    """Searches the enterprise knowledge base for policy documents."""
    global _embedding_model
    
    chroma_url = os.environ.get("CHROMA_SERVER_URL", "").rstrip("/")
    collection_name = os.environ.get("CHROMA_COLLECTION", "bank_abc_knowledge")
    
    # Extract the token just like the backend does
    cml_token = (
        os.environ.get("CML_TOKEN") 
        or os.environ.get("CDSW_API_KEY") 
        or os.environ.get("CHROMA_SERVER_TOKEN") 
        or ""
    ).strip()

    if not chroma_url or not cml_token:
        return "Error: Missing CHROMA_SERVER_URL or CML_TOKEN in environment."

    # Mimic the CMLChromaClient from ingest_knowledge.py
    session = requests.Session()
    session.verify = False  # Bypass internal SSL
    session.headers.update({"Authorization": f"Bearer {cml_token}"})

    try:
        # 1. Get Collection ID directly via REST (Bypassing chromadb.HttpClient)
        get_coll_url = f"{chroma_url}/api/v1/collections/{collection_name}"
        res = session.get(get_coll_url, timeout=15)
        if res.status_code != 200:
            return f"Error: Failed to connect to ChromaDB. Status {res.status_code}"
        
        collection_id = res.json()["id"]

        # 2. Embed the User's Query
        if _embedding_model is None:
            _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
        query_vector = _embedding_model.encode([query]).tolist()

        # 3. Query the Vector Database
        query_url = f"{chroma_url}/api/v1/collections/{collection_id}/query"
        payload = {
            "query_embeddings": query_vector,
            "n_results": n_results,
            "include": ["documents", "metadatas"]
        }
        query_res = session.post(query_url, json=payload, timeout=30)
        query_res.raise_for_status()

        # 4. Return formatted context back to CrewAI
        documents = query_res.json().get("documents", [[]])[0]
        if not documents:
            return "No matching context found in the knowledge base."

        return "\n\n---\n\n".join(documents)
        
    except Exception as e:
        return f"Error executing RAG search: {str(e)}"