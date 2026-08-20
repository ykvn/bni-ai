import os
import json
import yaml
from shared.embed_client import get_embedding_vector, rerank_documents
from shared.qdrant_client import QdrantClient
from shared.cml_auth import get_cml_token

def search_mf_catalog(
    user_query: str, 
    top_candidates: int = 50,
    max_metrics: int = 3,
    max_dimensions: int = 20,
    max_entities: int = 10,
    absolute_min_score: float = 0.001,
    relative_threshold_ratio: float = 0.15
) -> str:
    """
    Searches Qdrant for MetricFlow items, applies Cross-Encoder reranking,
    and enforces score thresholds to filter out off-topic queries before applying Category Quotas.
    """
    cml_token = get_cml_token()
    embed_url = os.getenv("EMBED_RERANK_URL", "").rstrip("/")
    vectordb_url = os.getenv("VECTORDB_SERVER_URL", "").rstrip("/")
    collection_name = os.getenv("MF_CATALOG_COLLECTION", "mf_catalog")

    empty_response = yaml.dump({"matched_metrics": [], "matched_dimensions": [], "matched_entities": []})

    try:
        # 1. Fetch broad candidate net
        query_vector = get_embedding_vector(user_query, engine_url=embed_url, cml_token=cml_token, timeout=15)
        qdrant_client = QdrantClient(base_url=vectordb_url, token=cml_token)
        
        results = qdrant_client.search(
            collection_name,
            query_vector,
            top_k=top_candidates,
            token=cml_token,
        )
        
        if not results or (isinstance(results, list) and len(results) > 0 and "error" in results[0]):
            return empty_response

        # 2. Parse Candidates
        candidate_items = []
        rerank_docs = []

        for point in results:
            payload = point.get("payload", {})
            raw_json = payload.get("raw_json")
            
            if raw_json:
                try:
                    item = json.loads(raw_json)
                    item_type = item.get("item_type", "metric")
                    
                    if item_type == "metric":
                        doc_str = f"Metric: {item.get('name', '')} | Label: {item.get('label', '')} | Description: {item.get('description', '')}"
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
            return empty_response

        # 3. Apply Cross-Encoder Reranking and Thresholding
        filtered_candidates = []
        try:
            rerank_results = rerank_documents(
                query=user_query,
                documents=rerank_docs,
                engine_url=embed_url,
                cml_token=cml_token,
                top_n=len(rerank_docs),
                timeout=15,
            )
            
            if rerank_results:
                # Find the global highest score among candidates
                top_score = max([hit.get("score", hit.get("relevance_score", 0.0)) for hit in rerank_results], default=0.0)
                
                # Calculate threshold (at least absolute_min_score and relative_threshold_ratio of top score)
                score_threshold = max(top_score * relative_threshold_ratio, absolute_min_score)

                for hit in rerank_results:
                    score = hit.get("score", hit.get("relevance_score", 0.0))
                    idx = hit.get("index")
                    
                    # Keep item only if it meets the score threshold
                    if score >= score_threshold and idx is not None and idx < len(candidate_items):
                        filtered_candidates.append(candidate_items[idx])

        except Exception as e:
            print(f"⚠️ Reranker failed, falling back to raw vector results: {e}", flush=True)
            filtered_candidates = candidate_items

        if not filtered_candidates:
            return empty_response

        # 4. Enforce Category Quotas on Filtered Candidates
        metrics = []
        dimensions = []
        entities = []

        for item in filtered_candidates:
            item_type = item.pop("item_type", None)
            
            if item_type == "metric" and len(metrics) < max_metrics:
                metrics.append(item)
            elif item_type == "dimension" and len(dimensions) < max_dimensions:
                dimensions.append(item)
            elif item_type == "entity" and len(entities) < max_entities:
                entities.append(item)

            if (len(metrics) >= max_metrics and 
                len(dimensions) >= max_dimensions and 
                len(entities) >= max_entities):
                break

        catalog_output = {
            "matched_metrics": metrics,
            "matched_dimensions": dimensions,
            "matched_entities": entities
        }

        return yaml.dump(catalog_output, sort_keys=False, default_flow_style=False)
        
    except Exception as e:
        return yaml.dump({"error": str(e)})