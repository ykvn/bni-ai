import os
import json
import yaml
from shared.embed_client import get_embedding_vector
from shared.qdrant_client import QdrantClient
from shared.cml_auth import get_cml_token

def search_mf_catalog(user_query: str, top_k: int = 10) -> str:
    """
    Searches Qdrant for the most relevant MetricFlow metrics, dimensions, and entities
    based on user intent.
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
        
        if results and isinstance(results, list) and len(results) > 0 and "error" in results[0]:
            return yaml.dump({"error": results[0]["error"]})

        metrics = []
        dimensions = []
        entities = []

        # Parse raw_json payloads and organize by item_type
        for point in results:
            payload = point.get("payload", {})
            raw_json = payload.get("raw_json")
            
            if raw_json:
                try:
                    item = json.loads(raw_json)
                    item_type = item.pop("item_type", None)
                    
                    if item_type == "metric":
                        metrics.append(item)
                    elif item_type == "dimension":
                        dimensions.append(item)
                    elif item_type == "entity":
                        entities.append(item)
                    else:
                        # Fallback for untagged items
                        metrics.append(item)
                except Exception:
                    continue

        # Format output into clean sections for the LLM
        catalog_output = {
            "matched_metrics": metrics,
            "matched_dimensions": dimensions,
            "matched_entities": entities
        }

        return yaml.dump(catalog_output, sort_keys=False, default_flow_style=False)
        
    except Exception as e:
        return yaml.dump({"error": str(e)})