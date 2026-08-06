from app.tools.schema_utils import get_smart_schema_context

def get_database_schema(user_question: str, top_k: int = 5, top_n: int = 15) -> str:
    """
    Dynamically retrieves only the relevant database schema tables based on the user's question.
    """
    return get_smart_schema_context(
        user_query=user_question, 
        top_tables=top_k, 
        top_columns=top_n
    )