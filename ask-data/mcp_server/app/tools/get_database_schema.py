from app.tools.schema_utils import get_smart_schema_context
from app.tools.search_golden_queries import search_golden_queries

def get_database_schema(user_question: str) -> str:
    """
    Dynamically retrieves relevant database schema tables AND matching golden query templates 
    based on the user's question.
    """
    # 1. Fetch pruned schema context
    schema_context = get_smart_schema_context(user_query=user_question)
    
    # 2. Fetch verified golden queries matching the intent
    try:
        golden_context = search_golden_queries(user_question=user_question)
        
        # Append golden query examples if valid results were found
        if golden_context and "No verified golden queries found" not in golden_context:
            return f"{schema_context}\n\n{golden_context}"
    except Exception as e:
        print(f"⚠️ Warning: Golden query lookup failed: {e}")
        
    return schema_context