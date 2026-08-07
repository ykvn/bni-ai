raise RuntimeError("🔥 I AM THE CORRECT FILE 🔥")
import os
import yaml
import requests
import urllib3

# Suppress SSL certificate verification warnings in enterprise CML environments
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_smart_schema_context(
    user_query: str, 
    top_tables: int = 5, 
    top_columns: int = 15, 
    threshold: float = 0.1
) -> str:
    """
    Executes STRICT 2-Stage Retrieval reading environment variables directly from .env:
    1. Vector Search (Qdrant) via VECTORDB_SERVER_URL & SCHEMA_COLLECTION
    2. Cross-Encoder Reranking via EMBED_RERANK_URL
    3. Reconstructs a pruned YAML schema with Primary/Foreign Key guardrails.
    (STRICT MODE: No file fallbacks. Fails explicitly if Vector DB is unreachable.)
    """
    
    # ---------------------------------------------------------
    # Load Environment Variables Exactly as Defined in .env
    # ---------------------------------------------------------
    cml_token = (os.getenv("CML_TOKEN") or os.getenv("CDSW_API_KEY") or "").strip()
    embed_url = os.getenv("EMBED_RERANK_URL", "").rstrip("/")
    vectordb_url = os.getenv("VECTORDB_SERVER_URL", "").rstrip("/")
    schema_collection = os.getenv("SCHEMA_COLLECTION", "bni_schema_definitions")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cml_token}"
    }

    # ==========================================
    # STAGE 1: VECTOR SEARCH (Find Relevant Tables)
    # ==========================================
    print(f"🔍 STAGE 1: Embedding query to search Qdrant '{schema_collection}' for Top {top_tables} tables...")
    
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
        error_msg = f"CRITICAL ERROR: Embedding API failed: {e}"
        print(f"🚨 {error_msg}")
        return yaml.dump({"error": error_msg}, sort_keys=False)

    # Search Qdrant Collection via REST API using VECTORDB_SERVER_URL
    qdrant_headers = {
        "api-key": cml_token, 
        "Authorization": f"Bearer {cml_token}", # Required for CML Ingress Proxy
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
        return yaml.dump({"error": error_msg}, sort_keys=False)

    # Extract `raw_yaml` metadata stored during ingestion
    retrieved_tables = []
    for point in retrieved_points:
        payload = point.get("payload", {})
        raw_yaml_str = payload.get("raw_yaml")
        if raw_yaml_str:
            retrieved_tables.append(yaml.safe_load(raw_yaml_str))

    if not retrieved_tables:
        error_msg = "CRITICAL ERROR: No matching tables found in Qdrant (or missing 'raw_yaml' payload)."
        print(f"🚨 {error_msg}")
        return yaml.dump({"error": error_msg}, sort_keys=False)

    # ==========================================
    # STAGE 2: RERANKING (Find Relevant Columns)
    # ==========================================
    print("🧠 STAGE 2: Flattening retrieved tables for Cross-Encoder Reranker...")
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
        rerank_payload = {
            "query": user_query,
            "documents": documents,
            "top_n": top_columns
        }
        
        rerank_res = requests.post(
            f"{embed_url}/v1/rerank", 
            json=rerank_payload, 
            headers=headers, 
            verify=False,
            timeout=15
        )
        rerank_res.raise_for_status()
        rerank_results = rerank_res.json().get("results", [])
    except Exception as e:
        print(f"⚠️ Reranker failed: {e}. Returning un-pruned Vector DB tables directly.")
        return yaml.dump({"tables": retrieved_tables}, sort_keys=False)

    winning_columns = []
    for hit in rerank_results:
        score = hit.get("score", 0.0)
        idx = hit.get("index")
        if score > threshold and idx is not None:
            winning_columns.append(mapping[idx])

    if not winning_columns:
        return yaml.dump({"tables": retrieved_tables}, sort_keys=False)

    # ==========================================
    # STAGE 3: PRUNE & RECONSTRUCT
    # ==========================================
    print("🛡️ STAGE 3: Reconstructing YAML and injecting required Primary/Foreign Keys...")
    relevant_table_names = {item['table'] for item in winning_columns}
    pruned_tables = []

    for table in retrieved_tables:
        table_name = table.get("name")
        
        if table_name in relevant_table_names:
            selected_col_names = {item['column'] for item in winning_columns if item['table'] == table_name}
            mandatory_columns = []
            
            for col in table.get("columns", []):
                is_selected = col.get("name") in selected_col_names
                is_primary_key = col.get("primary_key") is True
                is_foreign_key = "references" in col
                
                if is_selected or is_primary_key or is_foreign_key:
                    mandatory_columns.append(col)
            
            pruned_tables.append({
                "name": table_name,
                "description": table.get("description"),
                "columns": mandatory_columns
            })

    final_schema = {
        "database_type": "Cloudera Impala",
        "tables": pruned_tables
    }
    
    return yaml.dump(final_schema, sort_keys=False, default_flow_style=False)