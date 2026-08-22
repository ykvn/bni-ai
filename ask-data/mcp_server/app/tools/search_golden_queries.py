import os
from app.tools.qdrant_client import search_documents, rerank_documents
from shared.search_utils import calculate_unified_score

def search_golden_queries(
    user_question: str, top_k: int = 5, top_n: int = 3, min_relevance_score: float = 0.25
) -> str:
    top_k = int(os.getenv("GOLDEN_TOP_K", top_k))
    top_n = int(os.getenv("GOLDEN_TOP_N", top_n))
    min_relevance_score = float(os.getenv("GOLDEN_MIN_RELEVANCE_SCORE", min_relevance_score))
    collection_name = os.getenv("GOLDEN_COLLECTION", "bni_golden_queries")
    
    raw_results = search_documents(query=user_question, collection_name=collection_name, top_k=top_k)
    if not raw_results or "error" in raw_results[0]:
        return "No verified golden queries found for this intent."

    for doc in raw_results:
        payload = doc.get("raw_payload", {})
        target_text = payload.get("description", "").strip() or payload.get("user_intent", "").strip()
        if target_text:
            doc["page_content"] = doc["text"] = doc["excerpt"] = doc["_eval_desc"] = target_text

    reranked = rerank_documents(query=user_question, raw_documents=raw_results, top_n=top_n)
    valid_examples = []
    
    for doc in reranked:
        final_score = calculate_unified_score(
            raw_vector_score=doc.get("score", 0.0),
            raw_rerank_score=doc.get("rerank_score", doc.get("score", 0.0)),
            description=doc.get("_eval_desc", ""),
            user_query=user_question
        )
        doc["final_score"] = final_score
        if final_score >= min_relevance_score: valid_examples.append(doc)

    if not valid_examples:
        return "No verified golden queries found for this intent."
        
    valid_examples.sort(key=lambda x: x["final_score"], reverse=True)
    output = ["### VERIFIED GOLDEN QUERIES (Use as references for SQL syntax) ###\n"]
    
    for idx, doc in enumerate(valid_examples):
        payload = doc.get("raw_payload", {})
        output.append(f"-- Example {idx+1} (Relevance Score: {doc.get('final_score', 0.0)}) --")
        output.append(f"Intent: {payload.get('user_intent', 'Unknown Intent')}")
        if desc := payload.get("description", ""): output.append(f"Description: {desc}")
        output.append(f"SQL:\n{payload.get('sql_template', 'SQL NOT FOUND')}\n")
        
    return "\n".join(output)