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

# Common stop words to exclude from keyword scoring
INDONESIAN_STOP_WORDS = {
    "tampilkan", "dengan", "yang", "untuk", "pada", "adalah", 
    "seperti", "atau", "dalam", "saja", "secara", "karena", "di", "ke"
}

def search_mf_catalog(
    user_query: str, 
    top_candidates: int = 300,  # 👈 Set to 300 to fetch the FULL catalog (prevents early vector pruning)
    max_metrics: int = 10,
    max_dimensions: int = 20,
    max_entities: int = 10,
    absolute_min_score: float = 0.000,
    relative_threshold_ratio: float = 0.00
) -> str:
    """
    Searches Qdrant for MetricFlow items, prioritizing exact description phrase and keyword matches
    over raw vector similarity before applying Cross-Encoder reranking.
    """
    top_candidates = int(os.getenv("MF_TOP_CANDIDATES", top_candidates))
    max_metrics = int(os.getenv("MF_MAX_METRICS", max_metrics))
    max_dimensions = int(os.getenv("MF_MAX_DIMENSIONS", max_dimensions))
    max_entities = int(os.getenv("MF_MAX_ENTITIES", max_entities))
    absolute_min_score = float(os.getenv("MF_ABSOLUTE_MIN_SCORE", absolute_min_score))
    relative_threshold_ratio = float(os.getenv("MF_RELATIVE_THRESHOLD_RATIO", relative_threshold_ratio))

    cml_token = get_cml_token()
    embed_url = os.getenv("EMBED_RERANK_URL", "").rstrip("/")
    vectordb_url = os.getenv("VECTORDB_SERVER_URL", "").rstrip("/")
    collection_name = os.getenv("MF_CATALOG_COLLECTION", "mf_catalog")

    # 1. Clean query and extract words + 2-word exact phrases (e.g. "nilai transaksi")
    clean_query = user_query.lower()
    for char in ['?', '!', '.', ',', ':', ';', '/', '-', '_', '(', ')', '[', ']']:
        clean_query = clean_query.replace(char, ' ')
    
    query_words = [w for w in clean_query.split() if len(w) > 2 and w not in INDONESIAN_STOP_WORDS]
    query_tokens = set(query_words)

    query_phrases = []
    for i in range(len(query_words) - 1):
        query_phrases.append(f"{query_words[i]} {query_words[i+1]}")

    try:
        # 2. Fetch full catalog candidate net (top_k=300 ensures zero metrics are dropped blindly)
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

        # 3. Parse Candidates & Inspect Description & Label Text FIRST
        candidate_items = []
        rerank_docs = []
        description_boost_scores = []

        for point in results:
            payload = point.get("payload", {})
            raw_json = payload.get("raw_json")
            
            if raw_json:
                try:
                    item = json.loads(raw_json)
                    item_type = item.get("item_type", "metric")
                    
                    item_name = item.get('name', '')
                    item_label = item.get('label', '')
                    item_desc = item.get('description', '')

                    if item_type == "metric":
                        time_dim = item.get('default_time_dimension', '')
                        doc_str = f"Metric: {item_name} | Label: {item_label} | Description: {item_desc} | Time Dimension: {time_dim}"
                    elif item_type == "dimension":
                        doc_str = f"Dimension Path: {item_name} | Description: {item_desc} | Type: {item.get('data_type', '')}"
                    elif item_type == "entity":
                        doc_str = f"Entity Key: {item_name} | Key Type: {item.get('type', '')} | Table: {item.get('semantic_model', '')}"
                    else:
                        doc_str = f"Catalog Item: {item_name} | Description: {item_desc}"

                    # Clean description/label string for phrase matching
                    searchable_text = f"{item_name} {item_label} {item_desc}".lower()
                    for char in ['?', '!', '.', ',', ':', ';', '/', '-', '_', '(', ')', '[', ']', '|']:
                        searchable_text = searchable_text.replace(char, ' ')

                    # A. EXACT MULTI-WORD PHRASE MATCH (e.g. "nilai transaksi") -> Massive +3.0 Boost
                    phrase_matches = sum(1 for phrase in query_phrases if phrase in searchable_text)

                    # B. SINGLE TOKEN INTERSECTION (excluding stop words) -> +0.5 per token
                    item_tokens = set(w for w in searchable_text.split() if len(w) > 2 and w not in INDONESIAN_STOP_WORDS)
                    token_matches = len(query_tokens.intersection(item_tokens))

                    # Combine into a description priority score
                    desc_score = (phrase_matches * 3.0) + (token_matches * 0.5)

                    candidate_items.append(item)
                    rerank_docs.append(doc_str)
                    description_boost_scores.append(desc_score)
                except Exception:
                    continue

        if not candidate_items:
            return NO_MF_RESPONSE

        # 4. Cross-Encoder Reranking with Description Priority Boost
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
                        desc_boost = description_boost_scores[idx]
                        
                        # Apply description priority directly to final score
                        final_score = raw_score + desc_boost

                        boosted_hits.append({
                            "item": candidate_items[idx],
                            "score": final_score
                        })

                # Sort DESC: Exact description matches win unconditionally
                boosted_hits.sort(key=lambda x: x["score"], reverse=True)

                if boosted_hits:
                    top_score = boosted_hits[0]["score"]
                    score_threshold = max(top_score * relative_threshold_ratio, absolute_min_score)

                    for hit_data in boosted_hits:
                        if hit_data["score"] >= score_threshold:
                            filtered_candidates.append(hit_data["item"])

        except Exception as e:
            filtered_candidates = candidate_items

        if not filtered_candidates:
            return NO_MF_RESPONSE

        # 5. Enforce Category Quotas
        metrics = []
        dimensions = []
        entities = []

        for item in filtered_candidates:
            item_type = item.pop("item_type", None)
            item.pop("raw_name", None)
            
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

        if not metrics and not dimensions and not entities:
            return NO_MF_RESPONSE

        return yaml.dump({
            "matched_metrics": metrics,
            "matched_dimensions": dimensions,
            "matched_entities": entities
        }, sort_keys=False, default_flow_style=False)
        
    except Exception as e:
        return yaml.dump({"error": str(e)})