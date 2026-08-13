import os
import yaml
from shared.embed_client import get_embedding_vector
from shared.qdrant_client import QdrantClient
from shared.cml_auth import get_cml_token

def search_mf_catalog(user_query: str, top_k: int = 6) -> str:
    """
    Searches Qdrant for the most relevant MetricFlow metrics and dimensions based on user intent.
    """
    cml_token = get_cml_token()
    embed_url = os.getenv("EMBED_RERANK_URL", "").rstrip("/")
    vectordb_url = os.getenv("VECTORDB_SERVER_URL", "").rstrip("/")
    collection_name = os.getenv("MF_CATALOG_COLLECTION", "mf_catalog")

    try:
        query_vector = get_embedding_vector(user_query, engine_url=embed_url, cml_token=cml_token, timeout=15)
        qdrant_client = QdrantClient(base_url=vectordb_url, token=cml_token)
        
        results = qdrant_client.search(
            collection_name,
            query_vector,
            top_k=top_k,
            token=cml_token,
        )
        
        if results and "error" in results[0]:
            return yaml.dump({"error": results[0]["error"]})

        # Format the output for the LLM natively
        catalog_items = []
        for point in results:
            payload = point.get("payload", {})
            raw_yaml = payload.get("raw_yaml")
            if raw_yaml:
                catalog_items.append(yaml.safe_load(raw_yaml))

        return yaml.dump({"matched_metrics_and_dimensions": catalog_items}, sort_keys=False, default_flow_style=False)
        
    except Exception as e:
        return yaml.dump({"error": str(e)})