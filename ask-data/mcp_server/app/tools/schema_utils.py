import os
import yaml
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def _normalize_table_dict(table: dict, columns: list) -> dict:
    """Helper to enforce strict key order for tables (name -> description -> columns) and columns (name -> type -> primary_key -> references -> description)."""
    clean_cols = []
    for col in columns:
        clean_col = {}
        if "name" in col:
            clean_col["name"] = col["name"]
        if "type" in col:
            clean_col["type"] = col["type"]
        if col.get("primary_key") is True:
            clean_col["primary_key"] = True
        if "references" in col:
            clean_col["references"] = col["references"]
        if "description" in col:
            clean_col["description"] = col["description"]
        clean_cols.append(clean_col)

    return {
        "name": table.get("name"),
        "description": table.get("description"),
        "columns": clean_cols
    }

def get_smart_schema_context(
    user_query: str, 
    top_tables: int = 3, 
    top_columns: int = 1, 
    threshold: float = 0.0
) -> str:
    cml_token = (os.getenv("CML_TOKEN") or os.getenv("CDSW_API_KEY") or "").strip()
    embed_url = os.getenv("EMBED_RERANK_URL", "").rstrip("/")
    vectordb_url = os.getenv("VECTORDB_SERVER_URL", "").rstrip("/")
    schema_collection = os.getenv("SCHEMA_COLLECTION", "bni_schema_definitions")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cml_token}"
    }

    # ==========================================
    # STAGE 1: VECTOR SEARCH (Find Tables)
    # ==========================================
    try:
        embed_res = requests.post(
            f"{embed_url}/v1/embeddings", 
            json={"input": user_query}, 
            headers=headers, 
            verify=False,
            timeout=15
        )
        embed_res.raise_for_status()
        query_vector = embed_res.json().get("embeddings")
        if query_vector and isinstance(query_vector[0], list): 
            query_vector = query_vector[0]
    except Exception as e:
        error_msg = f"CRITICAL ERROR: Embedding API failed at {embed_url}: {e}"
        print(f"🚨 {error_msg}")
        return yaml.dump({"database_type": "Cloudera Impala", "error": error_msg}, sort_keys=False)

    qdrant_headers = {
        "api-key": cml_token, 
        "Authorization": f"Bearer {cml_token}",
        "Content-Type": "application/json"
    }

    qdrant_payload = {
        "vector": query_vector,
        "limit": top_tables,
        "with_payload": True
    }
    
    try:
        qdrant_res = requests.post(
            f"{vectordb_url}/collections/{schema_collection}/points/search",
            json=qdrant_payload,
            headers=qdrant_headers,
            verify=False,
            timeout=15
        )
        qdrant_res.raise_for_status()
        retrieved_points = qdrant_res.json().get("result", [])
    except Exception as e:
        error_msg = f"CRITICAL ERROR: Qdrant search failed at {vectordb_url}: {e}"
        print(f"🚨 {error_msg}")
        return yaml.dump({"database_type": "Cloudera Impala", "error": error_msg}, sort_keys=False)

    retrieved_tables = []
    for point in retrieved_points:
        payload = point.get("payload", {})
        raw_yaml_str = payload.get("raw_yaml")
        if raw_yaml_str:
            retrieved_tables.append(yaml.safe_load(raw_yaml_str))

    if not retrieved_tables:
        error_msg = "CRITICAL ERROR: No matching tables found in Qdrant."
        print(f"🚨 {error_msg}")
        return yaml.dump({"database_type": "Cloudera Impala", "error": error_msg}, sort_keys=False)

    # ==========================================
    # STAGE 2: RERANKING (Find Columns)
    # ==========================================
    documents = []
    mapping = []
    for table in retrieved_tables:
        t_name = table.get("name")
        for col in table.get("columns", []):
            c_name = col.get("name")
            doc_string = f"Table: {t_name} | Column: {c_name} | Type: {col.get('type')} | Description: {col.get('description', '')}"
            documents.append(doc_string)
            mapping.append({"table": t_name, "column": c_name})

    try:
        rerank_payload = {"query": user_query, "documents": documents, "top_n": top_columns}
        rerank_res = requests.post(
            f"{embed_url}/v1/rerank", 
            json=rerank_payload, 
            headers=headers, 
            verify=False,
            timeout=15
        )
        rerank_res.raise_for_status()
        
        res_data = rerank_res.json()
        if isinstance(res_data, list):
            rerank_results = res_data
        elif isinstance(res_data, dict):
            rerank_results = res_data.get("results", res_data.get("data", []))
        else:
            rerank_results = []
            
    except Exception as e:
        # NO FALLBACK: Return explicit error immediately
        error_msg = f"CRITICAL ERROR: Reranker API call failed at {embed_url}/v1/rerank: {e}"
        print(f"🚨 {error_msg}")
        return yaml.dump({"database_type": "Cloudera Impala", "error": error_msg}, sort_keys=False)

    winning_columns = []
    for hit in rerank_results:
        score = hit.get("score", hit.get("relevance_score", 0.0))
        idx = hit.get("index")
        if idx is not None and score >= threshold:
            winning_columns.append(mapping[idx])

    if not winning_columns:
        # NO FALLBACK: Return explicit error if no columns match
        error_msg = f"CRITICAL ERROR: Reranker returned 0 valid matching columns for top_n={top_columns}."
        print(f"🚨 {error_msg}")
        return yaml.dump({"database_type": "Cloudera Impala", "error": error_msg}, sort_keys=False)

    # ==========================================
    # STAGE 3: RECONSTRUCT STRICT PRUNED SCHEMA
    # ==========================================
    relevant_table_names = {item['table'] for item in winning_columns}
    pruned_tables = []

    for table in retrieved_tables:
        table_name = table.get("name")
        if table_name in relevant_table_names:
            selected_col_names = {item['column'] for item in winning_columns if item['table'] == table_name}
            mandatory_columns = [
                col for col in table.get("columns", [])
                if col.get("name") in selected_col_names or col.get("primary_key") or "references" in col
            ]
            pruned_tables.append(_normalize_table_dict(table, mandatory_columns))

    final_schema = {
        "database_type": "Cloudera Impala",
        "tables": pruned_tables
    }
    
    return yaml.dump(final_schema, sort_keys=False, default_flow_style=False)