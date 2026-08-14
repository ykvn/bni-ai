import yaml
from app.tools.schema_utils import get_smart_schema_context
from app.tools.search_golden_queries import search_golden_queries

def clean_schema_yaml(raw_yaml_str: str) -> str:
    """Strips internal reranking score fields from the pure YAML string."""
    try:
        data = yaml.safe_load(raw_yaml_str)
        if isinstance(data, dict) and "tables" in data:
            for table in data["tables"]:
                table.pop("score", None)
                for col in table.get("columns", []):
                    col.pop("score", None)
        return yaml.dump(data, sort_keys=False, default_flow_style=False)
    except Exception:
        return raw_yaml_str

def get_database_schema(user_question: str) -> str:
    # 1. Fetch pure YAML schema context
    raw_schema_context = get_smart_schema_context(user_query=user_question)
    
    # 2. Clean the score fields while it is pure YAML
    cleaned_schema = clean_schema_yaml(raw_schema_context)
    
    # 3. Fetch golden queries and append
    try:
        golden_context = search_golden_queries(user_question=user_question)
        if golden_context and "No verified golden queries found" not in golden_context:
            return f"{cleaned_schema}\n\n{golden_context}"
    except Exception as e:
        print(f"⚠️ Warning: Golden query lookup failed: {e}")
        
    return cleaned_schema