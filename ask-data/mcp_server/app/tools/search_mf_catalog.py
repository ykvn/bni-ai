import os
import json
import yaml
from shared.embed_client import get_embedding_vector, rerank_documents
from shared.qdrant_client import QdrantClient
from shared.cml_auth import get_cml_token

def search_mf_catalog(user_query: str, top_k: int = 50, top_n: int = 20) -> str:
    """
    Searches Qdrant for MetricFlow metrics, dimensions, and entities based on user intent,
    and applies Cross-Encoder reranking to return the most accurate items.
    """
    cml_token = get_cml_token()
    embed_url = os.getenv("EMBED_RERANK_URL", "").rstrip("/")
    vectordb_url = os.getenv("VECTORDB_SERVER_URL", "").rstrip("/")
    collection_name = os.getenv("MF_CATALOG_COLLECTION", "mf_catalog")

    try:
        # Stage 1: Broad Candidate Fetching via Dense Vector Search
        query_vector = get_embedding_vector(user_query, engine_url=embed_url, cml_token=cml_token, timeout=15)
        qdrant_client = QdrantClient(base_url=vectordb_url, token=cml_token)
        
        results = qdrant_client.search(
            collection_name,
            query_vector,
            top_k=top_k,
            token=cml_token,
        )
        
        if not results or (isinstance(results, list) and len(results) > 0 and "error" in results[0]):
            return yaml.dump({"matched_metrics": [], "matched_dimensions": [], "matched_entities": []})

        # Stage 2: Parse Candidates and Format for Reranker
        candidate_items = []
        rerank_docs = []

        for point in results:
            payload = point.get("payload", {})
            raw_json = payload.get("raw_json")
            
            if raw_json:
                try:
                    item = json.loads(raw_json)
                    item_type = item.get("item_type", "metric")
                    
                    # Create structured text block for Cross-Encoder scoring
                    if item_type == "metric":
                        doc_str = f"Metric: {item.get('name', '')} | Label: {item.get('label', '')} | Description: {item.get('description', '')} | Synonyms: {item.get('synonyms', [])}"
                    elif item_type == "dimension":
                        doc_str = f"Dimension Path: {item.get('name', '')} | Description: {item.get('description', '')}"
                    elif item_type == "entity":
                        doc_str = f"Entity Key: {item.get('name', '')} | Key Type: {item.get('type', '')} | Table: {item.get('semantic_model', '')}"
                    else:
                        doc_str = f"Catalog Item: {item.get('name', '')} | Description: {item.get('description', '')}"

                    candidate_items.append(item)
                    rerank_docs.append(doc_str)
                except Exception:
                    continue

        if not candidate_items:
            return yaml.dump({"matched_metrics": [], "matched_dimensions": [], "matched_entities": []})

        # Stage 3: Apply Cross-Encoder Reranking
        try:
            rerank_results = rerank_documents(
                query=user_query,
                documents=rerank_docs,
                engine_url=embed_url,
                cml_token=cml_token,
                top_n=top_n,
                timeout=15,
            )
            
            # Select top_n candidates according to reranker order
            winning_items = []
            for hit in rerank_results:
                idx = hit.get("index")
                if idx is not None and idx < len(candidate_items):
                    winning_items.append(candidate_items[idx])
        except Exception as e:
            print(f"⚠️ Reranker failed, falling back to top_n vector results: {e}", flush=True)
            winning_items = candidate_items[:top_n]

        # Stage 4: Organize Matched Items for LLM Context Output
        metrics = []
        dimensions = []
        entities = []

        for item in winning_items:
            item_type = item.pop("item_type", None)
            
            if item_type == "metric":
                metrics.append(item)
            elif item_type == "dimension":
                dimensions.append(item)
            elif item_type == "entity":
                entities.append(item)
            else:
                metrics.append(item)

        catalog_output = {
            "matched_metrics": metrics,
            "matched_dimensions": dimensions,
            "matched_entities": entities
        }

        return yaml.dump(catalog_output, sort_keys=False, default_flow_style=False)
        
    except Exception as e:
        return yaml.dump({"error": str(e)})