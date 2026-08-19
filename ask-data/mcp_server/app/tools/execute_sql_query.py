import json

# Import the validated Cloudera Impala execution utility
from app.tools.impala_client import execute_query
from shared.sql_guard import sanitize_sql, is_read_only_query


def execute_sql_query(sql_query: str) -> str:
    # 1. Clean input normalization (Standard API boundary hygiene)
    query = sanitize_sql(sql_query)

    print(f"📝 Executing Agent Query:\n{query}")

    # 2. Security guardrail inspection copy
    if not is_read_only_query(query):
        return "Security Violation Error: Only read-only SELECT queries are authorized on this endpoint."

    try:
        raw_result = execute_query(query)
        records = raw_result.get("rows", [])
        return json.dumps(records, default=str)

    except Exception as e:
        return f"Cloudera Impala Engine Error: {str(e)}"