import os
import json
import re

# Import the validated Cloudera Impala execution utility
from app.tools.impala_client import execute_query

def execute_banking_query(sql_query: str) -> str:
    # 1. Clean input normalization (Standard API boundary hygiene)
    query = re.sub(r"^```(?:sql)?\s*|^sql\s*", "", sql_query.strip(), flags=re.IGNORECASE)
    query = re.sub(r"```$", "", query).strip()
    
    print(f"📝 Executing Agent Query:\n{query}")

    # 2. Security guardrail inspection copy
    clean_query = re.sub(r"--.*$", "", query, flags=re.MULTILINE)
    clean_query = re.sub(r"/\*.*?\*/", "", clean_query, flags=re.DOTALL).strip()
    clean_query = clean_query.rstrip(";").strip()
    clean_query_lower = clean_query.lower()
    
    forbidden_keywords = ["insert", "update", "delete", "drop", "alter", "truncate", "create", "merge"]
    has_forbidden_word = any(re.search(rf"\b{kw}\b", clean_query_lower) for kw in forbidden_keywords)
    is_read_only_start = clean_query_lower.startswith("select") or clean_query_lower.startswith("with")
    
    if has_forbidden_word or not is_read_only_start:
        return "Security Violation Error: Only read-only SELECT queries are authorized on this endpoint."
        
    try:
        raw_result = execute_query(query)
        records = raw_result.get("rows", [])
        return json.dumps(records, default=str)
            
    except Exception as e:
        return f"Cloudera Impala Engine Error: {str(e)}"