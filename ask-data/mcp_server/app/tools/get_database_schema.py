import os
from app.tools.qdrant_client import search_documents, rerank_documents

def get_database_schema(user_question: str, top_k: int = 10, top_n: int = 4) -> str:
    """
    Dynamically retrieves only the relevant database schema tables based on the user's question.
    Drastically reduces prompt token consumption and improves LLM TTFT (Time-to-First-Token).
    """
    collection_name = os.getenv("SCHEMA_COLLECTION", "bni_schema_definitions")
    
    # 1. Fetch candidate schema tables
    raw_results = search_documents(query=user_question, collection_name=collection_name, top_k=top_k)
    
    if not raw_results or "error" in raw_results[0]:
        return "Error: Could not retrieve database schema."

    # 2. Rerank the tables to find the exact columns needed for the query
    reranked = rerank_documents(query=user_question, raw_documents=raw_results, top_n=top_n)

    # 3. Reconstruct the YAML definition only for the top retrieved tables
    output = ["### RELEVANT DATABASE SCHEMA (YAML FORMAT) ###\n"]
    for doc in reranked:
        payload = doc.get("raw_payload", {})
        table_name = payload.get("table_name", "Unknown Table")
        raw_yaml = payload.get("raw_yaml", "")
        
        output.append(f"# Table: {table_name}")
        output.append(raw_yaml)
        output.append("-" * 40)
        
    return "\n".join(output)