import os
from app.tools.qdrant_client import search_documents, rerank_documents

# 🌟 NEW: Import Enterprise Scoring Module
from shared.search_utils import calculate_unified_score

def search_golden_queries(
    user_question: str,
    top_k: int = 5,
    top_n: int = 3,
    min_relevance_score: float = 0.01
) -> str:
    top_k = int(os.getenv("GOLDEN_TOP_K", top_k))
    top_n = int(os.getenv("GOLDEN_TOP_N", top_n))
    min_relevance_score = float(os.getenv("GOLDEN_MIN_RELEVANCE_SCORE", min_relevance_score))
    collection_name = os.getenv("GOLDEN_COLLECTION", "bni_golden_queries")
    
    # 1. Fetch broad candidate queries using dense vector similarity
    raw_results = search_documents(query=user_question, collection_name=collection_name, top_k=top_k)
    
    if not raw_results or "error" in raw_results[0]:
        return "No verified golden queries found for this intent."

    # 2. 🌟 STRICT DESCRIPTION ONLY (Safety fallback to intent if desc is fully blank)
    for doc in raw_results:
        payload = doc.get("raw_payload", {})
        desc = payload.get("description", "").strip()
        intent = payload.get("user_intent", "").strip()
        
        target_text = desc if desc else intent 

        if target_text:
            doc["page_content"] = target_text
            doc["text"] = target_text
            doc["excerpt"] = target_text
            doc["_eval_desc"] = target_text # Cache description for fusion scoring

    # 3. Re-score candidates against user_question using pure text
    reranked = rerank_documents(query=user_question, raw_documents=raw_results, top_n=top_n)

    # 4. 🌟 ENTERPRISE SCORE FUSION & FILTERING
    valid_examples = []
    for doc in reranked:
        raw_rerank_score = doc.get("rerank_score", doc.get("score", 0.0))
        raw_vector_score = doc.get("score", 0.0)  # Preserved from initial vector search
        desc = doc.get("_eval_desc", "")
        
        final_score = calculate_unified_score(
            raw_vector_score=raw_vector_score,
            raw_rerank_score=raw_rerank_score,
            description=desc,
            user_query=user_question
        )
        
        doc["final_score"] = final_score
        if final_score >= min_relevance_score:
            valid_examples.append(doc)

    if not valid_examples:
        return "No verified golden queries found for this intent."
        
    valid_examples.sort(key=lambda x: x["final_score"], reverse=True)

    # 5. Format into a clean LLM context block
    output = ["### VERIFIED GOLDEN QUERIES (Use as references for SQL syntax) ###\n"]
    for idx, doc in enumerate(valid_examples):
        payload = doc.get("raw_payload", {})
        intent = payload.get("user_intent", "Unknown Intent")
        description = payload.get("description", "")
        sql = payload.get("sql_template", "SQL NOT FOUND")
        score = doc.get("final_score", 0.0)
        
        output.append(f"-- Example {idx+1} (Relevance Score: {score}) --")
        output.append(f"Intent: {intent}")
        if description:
            output.append(f"Description: {description}")
        output.append(f"SQL:\n{sql}\n")
        
    return "\n".join(output)