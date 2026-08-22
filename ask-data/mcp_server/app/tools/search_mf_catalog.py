import os
import json
import yaml
from shared.embed_client import get_embedding_vector, rerank_documents
from shared.qdrant_client import QdrantClient
from shared.cml_auth import get_cml_token

# 🌟 NEW: Import Enterprise Scoring Module
from shared.search_utils import calculate_unified_score, compute_lexical_score

NO_MF_MATCH = "NO_MF_MATCH"
NO_MF_RESPONSE = "I am sorry, I don't have this information on my database."

def search_mf_catalog(
    user_query: str, 
    top_candidates: int = 500,
    max_metrics: int = 5,
    max_dimensions: int = 20,
    max_entities: int = 10,
    absolute_min_score: float = 0.001
) -> str:

    top_candidates = int(os.getenv("MF_TOP_CANDIDATES", top_candidates))
    max_metrics = int(os.getenv("MF_MAX_METRICS", max_metrics))
    max_dimensions = int(os.getenv("MF_MAX_DIMENSIONS", max_dimensions))
    max_entities = int(os.getenv("MF_MAX_ENTITIES", max_entities))
    absolute_min_score = float(os.getenv("MF_ABSOLUTE_MIN_SCORE", absolute_min_score))

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
            top_k=top_candidates,
            token=cml_token,
        )
        
        if not results or (isinstance(results, list) and len(results) > 0 and "error" in results[0]):
            return NO_MF_RESPONSE

        candidate_items = []

        # PRE-SORT USING VECTOR + LEXICAL ONLY (Fast filter before Neural Reranker)
        for point in results:
            payload = point.get("payload", {})
            raw_json = payload.get("raw_json")
            
            if raw_json:
                try:
                    item = json.loads(raw_json)
                    item_desc = item.get('description', '')
                    
                    qdrant_score = point.score if hasattr(point, 'score') else point.get("score", 0.0)
                    
                    # Estimate pre-score bypassing the slow neural model temporarily
                    s_vec = max(0.0, min(float(qdrant_score), 1.0))
                    s_lex = compute_lexical_score(item_desc, user_query)
                    pre_score = (0.50 * s_lex) + (0.15 * s_vec) 

                    candidate_items.append({
                        "item": item,
                        "description": item_desc,
                        "vector_score": qdrant_score,
                        "pre_score": pre_score
                    })
                except Exception:
                    continue

        if not candidate_items:
            return NO_MF_RESPONSE

        candidate_items.sort(key=lambda x: x["pre_score"], reverse=True)
        top_candidates_to_rerank = candidate_items[:100]
        
        # 🌟 STRICT DESCRIPTION ONLY TO RERANKER
        rerank_docs = [x["description"] for x in top_candidates_to_rerank]

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
                    raw_rerank_score = hit.get("score", hit.get("relevance_score", 0.0))
                    idx = hit.get("index")

                    if idx is not None and idx < len(top_candidates_to_rerank):
                        cand = top_candidates_to_rerank[idx]
                        
                        # 🌟 ENTERPRISE SCORE FUSION (0.0 to 1.0)
                        final_score = calculate_unified_score(
                            raw_vector_score=cand["vector_score"],
                            raw_rerank_score=raw_rerank_score,
                            description=cand["description"],
                            user_query=user_query
                        )

                        boosted_hits.append({
                            "item": cand["item"],
                            "score": final_score
                        })

                boosted_hits.sort(key=lambda x: x["score"], reverse=True)

                for hit_data in boosted_hits:
                    if hit_data["score"] >= absolute_min_score:
                        filtered_candidates.append(hit_data["item"])
            else:
                raise ValueError("Empty rerank results")

        except Exception as e:
            for c in top_candidates_to_rerank:
                filtered_candidates.append(c["item"])

        if not filtered_candidates:
            return NO_MF_RESPONSE

        metrics, dimensions, entities = [], [], []

        for item in filtered_candidates:
            item_type = item.pop("item_type", None)
            item.pop("raw_name", None)
            
            if item_type == "metric" and len(metrics) < max_metrics: metrics.append(item)
            elif item_type == "dimension" and len(dimensions) < max_dimensions: dimensions.append(item)
            elif item_type == "entity" and len(entities) < max_entities: entities.append(item)

            if len(metrics) >= max_metrics and len(dimensions) >= max_dimensions and len(entities) >= max_entities:
                break

        if not metrics and not dimensions and not entities:
            return NO_MF_RESPONSE

        return yaml.dump({
            "matched_metrics": metrics,
            "matched_dimensions": dimensions,
            "matched_entities": entities
        }, sort_keys=False, default_flow_style=False)
        
    except Exception as e:
        return yaml.dump({"error": str(e)})