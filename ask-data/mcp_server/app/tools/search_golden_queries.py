import os
from app.tools.qdrant_client import search_documents, rerank_documents

def search_golden_queries(user_question: str, top_k: int = 5, top_n: int = 2) -> str:
    """
    Searches the Golden Queries vector database for verified SQL templates matching the user's intent.
    Uses Cross-Encoder reranking to ensure high relevance.
    """
    collection_name = os.getenv("GOLDEN_COLLECTION", "bni_golden_queries")
    
    # 1. Fetch broad candidate queries using dense vector similarity
    raw_results = search_documents(query=user_question, collection_name=collection_name, top_k=top_k)
    
    if not raw_results or "error" in raw_results[0]:
        return "No verified golden queries found for this intent."

    # 2. Re-score candidates against the exact user question
    reranked = rerank_documents(query=user_question, raw_documents=raw_results, top_n=top_n)

    # 3. Format into a clean LLM context block
    output = ["### VERIFIED GOLDEN QUERIES (Use as references for SQL syntax) ###\n"]
    for idx, doc in enumerate(reranked):
        payload = doc.get("raw_payload", {})
        intent = payload.get("user_intent", "Unknown Intent")
        sql = payload.get("sql_template", "SQL NOT FOUND")
        score = doc.get("rerank_score", doc.get("score", 0))
        
        output.append(f"-- Example {idx+1} (Relevance Score: {score}) --")
        output.append(f"Intent: {intent}")
        output.append(f"SQL:\n{sql}\n")
        
    return "\n".join(output)