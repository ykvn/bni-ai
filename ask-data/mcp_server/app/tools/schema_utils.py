import os
import yaml

from shared.embed_client import get_embedding_vector, rerank_documents
from shared.qdrant_client import QdrantClient
from shared.cml_auth import get_cml_token


def _normalize_table_dict(table: dict, columns: list) -> dict:
    """Helper to enforce strict key order for tables and columns."""
    clean_cols = []
    for col in columns:
        clean_col = {}
        if "name" in col:
            clean_col["name"] = col["name"]
        if "score" in col:  # Preserve column score
            clean_col["score"] = col["score"]
        if "type" in col:
            clean_col["type"] = col["type"]
        if col.get("primary_key") is True:
            clean_col["primary_key"] = True
        if "references" in col:
            clean_col["references"] = col["references"]
        if "description" in col:
            clean_col["description"] = col["description"]
        clean_cols.append(clean_col)

    clean_table = {
        "name": table.get("name")
    }
    if "score" in table:  # Preserve table score
        clean_table["score"] = table["score"]

    clean_table["description"] = table.get("description")
    clean_table["columns"] = clean_cols

    return clean_table


def get_smart_schema_context(
    user_query: str,
    top_tables: int = 5,
    top_columns_per_table: int = 10,
    threshold: float = 0  # Calibrated for per-table Softmax distributions (~10-15 cols per table)
) -> str:
    cml_token = get_cml_token()
    embed_url = os.getenv("EMBED_RERANK_URL", "").rstrip("/")
    vectordb_url = os.getenv("VECTORDB_SERVER_URL", "").rstrip("/")
    schema_collection = os.getenv("SCHEMA_COLLECTION", "bni_schema_definitions")

    # ==========================================
    # STAGE 1: VECTOR SEARCH (Find Tables)
    # ==========================================
    try:
        query_vector = get_embedding_vector(user_query, engine_url=embed_url, cml_token=cml_token, timeout=15)
    except Exception as e:
        error_msg = f"CRITICAL ERROR: Embedding API failed at {embed_url}: {e}"
        print(f"🚨 {error_msg}")
        return yaml.dump({"database_type": "Cloudera Impala", "error": error_msg}, sort_keys=False)

    try:
        qdrant_client = QdrantClient(base_url=vectordb_url, token=cml_token)
        retrieved_points = qdrant_client.search(
            schema_collection,
            query_vector,
            top_k=top_tables,
            token=cml_token,
        )
        if retrieved_points and "error" in retrieved_points[0]:
            raise RuntimeError(retrieved_points[0]["error"])
    except Exception as e:
        error_msg = f"CRITICAL ERROR: Qdrant search failed at {vectordb_url}: {e}"
        print(f"🚨 {error_msg}")
        return yaml.dump({"database_type": "Cloudera Impala", "error": error_msg}, sort_keys=False)

    retrieved_tables = []
    for point in retrieved_points:
        payload = point.get("payload", {})
        point_score = point.get("score")  # Extract Qdrant Similarity Score
        raw_yaml_str = payload.get("raw_yaml")

        if raw_yaml_str:
            parsed_table = yaml.safe_load(raw_yaml_str)
            if point_score is not None:
                parsed_table["score"] = round(point_score, 4)  # Inject Table Score
            retrieved_tables.append(parsed_table)

    if not retrieved_tables:
        error_msg = "CRITICAL ERROR: No matching tables found in Qdrant."
        print(f"🚨 {error_msg}")
        return yaml.dump({"database_type": "Cloudera Impala", "error": error_msg}, sort_keys=False)

    # ==========================================
    # STAGE 2: PER-TABLE RERANKING & THRESHOLDING
    # ==========================================
    winning_columns = []
    for table in retrieved_tables:
        t_name = table.get("name")
        table_docs = []
        table_mapping = []

        for col in table.get("columns", []):
            c_name = col.get("name", "")
            c_desc = str(col.get("description", "")).strip() or "No description provided."
            c_type = col.get("type", "")

            # Front-load Column Name and Description for attention focus
            doc_string = f"Column Name: {c_name} | Description: {c_desc} | Table: {t_name} | Type: {c_type}"
            table_docs.append(doc_string)
            table_mapping.append({"table": t_name, "column": c_name})

        if not table_docs:
            continue

        try:
            # Rerank exclusively against this table's column pool
            rerank_results = rerank_documents(
                query=user_query,
                documents=table_docs,
                engine_url=embed_url,
                cml_token=cml_token,
                top_n=top_columns_per_table,
                timeout=15,
            )
            for hit in rerank_results:
                score = hit.get("score", hit.get("relevance_score", 0.0))
                idx = hit.get("index")
                
                # Apply threshold against per-table normalized Softmax score
                if idx is not None and score >= threshold:
                    col_data = table_mapping[idx].copy()
                    col_data["score"] = round(score, 4)
                    winning_columns.append(col_data)
        except Exception as e:
            print(f"⚠️ Per-table reranking failed for {t_name}: {e}")

    # ==========================================
    # STAGE 3: RECONSTRUCT PRUNED SCHEMA
    # ==========================================
    relevant_table_names = {item['table'] for item in winning_columns}
    pruned_tables = []

    for table in retrieved_tables:
        table_name = table.get("name")
        if table_name in relevant_table_names:
            col_scores = {item['column']: item['score'] for item in winning_columns if item['table'] == table_name}

            mandatory_columns = []
            for col in table.get("columns", []):
                c_name = col.get("name", "")
                c_desc = str(col.get("description", ""))

                # 1. Column passed per-table semantic reranking & threshold
                if c_name in col_scores:
                    col["score"] = col_scores[c_name]
                    mandatory_columns.append(col)
                # 2. Structural Safeguards (PK, FK, or DEFAULT_TIME_AXIS)
                elif (col.get("primary_key") or 
                      "references" in col or 
                      "DEFAULT_TIME_AXIS: True" in c_desc):
                    mandatory_columns.append(col)

            pruned_tables.append(_normalize_table_dict(table, mandatory_columns))

    final_schema = {
        "database_type": "Cloudera Impala",
        "tables": pruned_tables
    }

    return yaml.dump(final_schema, sort_keys=False, default_flow_style=False)