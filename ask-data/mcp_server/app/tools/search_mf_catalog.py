import os
import json
import yaml
from shared.embed_client import get_embedding_vector, rerank_documents
from shared.qdrant_client import QdrantClient
from shared.cml_auth import get_cml_token

# Internal marker emitted when the MetricFlow search returns no matching
# metrics, dimensions, or entities. The tool maps this to the plain
# user-facing refusal text (NO_MF_RESPONSE) so the front end displays the
# polite message instead of an empty `matched_*: []` YAML block.
NO_MF_MATCH = "NO_MF_MATCH"
NO_MF_RESPONSE = "I am sorry, I don't have this information on my database."

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
    Searches Qdrant for MetricFlow items, applies Lexical-Boosted Cross-Encoder reranking,
    and enforces score thresholds to filter out off-topic queries before applying Category Quotas.
    """
    cml_token = get_cml_token()
    embed_url = os.getenv("EMBED_RERANK_URL", "").rstrip("/")
    vectordb_url = os.getenv("VECTORDB_SERVER_URL", "").rstrip("/")
    collection_name = os.getenv("MF_CATALOG_COLLECTION", "mf_catalog")

    # Clean query tokens (replace underscores and ignore words <= 2 chars like "di", "ke")
    clean_query = user_query.lower()
    for char in ['?', '!', '.', ',', ':', ';', '/', '-', '_', '(', ')', '[', ']']:
        clean_query = clean_query.replace(char, ' ')
    query_tokens = set(word for word in clean_query.split() if len(word) > 2)

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
            print("🚫 [NO_MF_MATCH] No MetricFlow results or query returned an error.")
            return NO_MF_RESPONSE

        # 2. Parse Candidates with Enriched Context & Lexical Counts
        candidate_items = []
        rerank_docs = []
        token_match_counts = []

        for point in results:
            payload = point.get("payload", {})
            raw_json = payload.get("raw_json")
            
            if raw_json:
                try:
                    item = json.loads(raw_json)
                    item_type = item.get("item_type", "metric")
                    
                    # Enriched metadata strings for neural cross-encoder
                    if item_type == "metric":
                        time_dim = item.get('default_time_dimension', '')
                        doc_str = f"Metric: {item.get('name', '')} | Label: {item.get('label', '')} | Description: {item.get('description', '')} | Time Dimension: {time_dim}"
                    elif item_type == "dimension":
                        doc_str = f"Dimension Path: {item.get('name', '')} | Description: {item.get('description', '')} | Type: {item.get('data_type', '')}"
                    elif item_type == "entity":
                        doc_str = f"Entity Key: {item.get('name', '')} | Key Type: {item.get('type', '')} | Table: {item.get('semantic_model', '')}"
                    else:
                        doc_str = f"Catalog Item: {item.get('name', '')} | Description: {item.get('description', '')}"

                    # Lexical intersection count (split by underscore, ignore short words)
                    item_search_text = doc_str.lower()
                    for char in ['?', '!', '.', ',', ':', ';', '/', '-', '_', '(', ')', '[', ']']:
                        item_search_text = item_search_text.replace(char, ' ')
                    item_tokens = set(word for word in item_search_text.split() if len(word) > 2)
                    token_matches = len(query_tokens.intersection(item_tokens))

                    candidate_items.append(item)
                    rerank_docs.append(doc_str)
                    token_match_counts.append(token_matches)
                except Exception:
                    continue

        if not candidate_items:
            print("🚫 [NO_MF_MATCH] No candidate MetricFlow items parsed from results.")
            return NO_MF_RESPONSE

        # 3. Apply Cross-Encoder Reranking, Lexical Boosting, and Score Thresholding
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
                boosted_hits = []
                for hit in rerank_results:
                    raw_score = hit.get("score", hit.get("relevance_score", 0.0))
                    idx = hit.get("index")

                    if idx is not None and idx < len(candidate_items):
                        matches = token_match_counts[idx]
                        
                        # ADDITIVE BOOST: +0.5 absolute points per exact keyword match
                        # This mathematically forces exact matches to beat out neural noise.
                        boosted_score = raw_score + (0.5 * matches)

                        boosted_hits.append({
                            "item": candidate_items[idx],
                            "score": boosted_score
                        })

                # Sort DESC by boosted score
                boosted_hits.sort(key=lambda x: x["score"], reverse=True)

                if boosted_hits:
                    top_score = boosted_hits[0]["score"]
                    # Calculate relative thresholding floor
                    score_threshold = max(top_score * relative_threshold_ratio, absolute_min_score)

                    for hit_data in boosted_hits:
                        if hit_data["score"] >= score_threshold:
                            filtered_candidates.append(hit_data["item"])

        except Exception as e:
            print(f"⚠️ Reranker failed, falling back to raw vector results: {e}", flush=True)
            filtered_candidates = candidate_items

        if not filtered_candidates:
            print("🚫 [NO_MF_MATCH] No MetricFlow items survived score thresholding.")
            return NO_MF_RESPONSE

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

        # No-relevant-catalog guard
        if not metrics and not dimensions and not entities:
            print("🚫 [NO_MF_MATCH] No relevant metrics/dimensions/entities survived category quotas.")
            return NO_MF_RESPONSE

        catalog_output = {
            "matched_metrics": metrics,
            "matched_dimensions": dimensions,
            "matched_entities": entities
        }

        return yaml.dump(catalog_output, sort_keys=False, default_flow_style=False)
        
    except Exception as e:
        return yaml.dump({"error": str(e)})