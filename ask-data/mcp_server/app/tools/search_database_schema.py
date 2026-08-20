import os
import yaml

from shared.cml_auth import get_cml_token
from shared.embed_client import get_embedding_vector, rerank_documents
from shared.qdrant_client import QdrantClient

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

def _normalize_table_dict(table: dict, columns: list) -> dict:
    """Helper to enforce strict key order for tables and columns."""
    clean_cols = []
    for col in columns:
        clean_col = {}
        if "name" in col:
            clean_col["name"] = col["name"]
        if "score" in col:
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

    clean_table = {"name": table.get("name")}
    if "score" in table:
        clean_table["score"] = table["score"]

    clean_table["description"] = table.get("description")
    clean_table["columns"] = clean_cols

    return clean_table


def extract_sql_columns(text: str, valid_columns: set) -> set:
    """Extracts column names using sqlglot, falling back to strict set intersection."""
    extracted = set()
    text_lower = text.lower()
    
    if SQLGLOT_AVAILABLE:
        try:
            # Isolate SQL if embedded in YAML
            sql_start = text_lower.find("select ")
            sql_str = text[sql_start:] if sql_start != -1 else text
            
            # Parse the AST and find all Column nodes
            for stmt in sqlglot.parse(sql_str, read="impala"):
                if stmt:
                    for col in stmt.find_all(exp.Column):
                        if col.name:
                            extracted.add(col.name.lower())
            
            if extracted:
                return extracted.intersection(valid_columns)
        except Exception:
            pass  # Fallback if parsing fails

    # Fallback: No regex. Replace punctuation, split to words, intersect with valid schema.
    for char in ['(', ')', ',', '=', '<', '>', '!', "'", '"', ';', '\n', '\t']:
        text_lower = text_lower.replace(char, ' ')
        
    words = set(text_lower.split())
    return words.intersection(valid_columns)


def get_smart_schema_context(
    user_query: str,
    top_tables: int = 5,
    top_columns_per_table: int = 10,
    relative_threshold_ratio: float = 0.05
) -> str:
    cml_token = get_cml_token()
    embed_url = os.getenv("EMBED_RERANK_URL", "").rstrip("/")
    vectordb_url = os.getenv("VECTORDB_SERVER_URL", "").rstrip("/")
    schema_collection = os.getenv("SCHEMA_COLLECTION", "bni_schema_definitions")
    golden_collection = os.getenv("GOLDEN_QUERY_COLLECTION", "bni_golden_queries")

    # ==========================================
    # STAGE 1: VECTOR SEARCH (Find Tables & Golden Queries)
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
    valid_schema_columns = set()
    golden_query_cols = set()

    # 1a. Build retrieved_tables and collect all valid column names first
    for point in retrieved_points:
        payload = point.get("payload", {})
        point_score = point.get("score")
        raw_yaml_str = payload.get("raw_yaml")

        if raw_yaml_str:
            parsed_table = yaml.safe_load(raw_yaml_str)
            if point_score is not None:
                parsed_table["score"] = round(point_score, 4)
            retrieved_tables.append(parsed_table)
            
            # Populate valid columns for filtering
            for col in parsed_table.get("columns", []):
                if "name" in col:
                    valid_schema_columns.add(str(col["name"]).lower())

    # 1b. Query Golden Query collection directly to harvest referenced SQL columns
    target_collections = [golden_collection, "bni_golden_queries", "golden_queries"]
    for g_col in dict.fromkeys(target_collections):
        try:
            golden_points = qdrant_client.search(
                g_col,
                query_vector,
                top_k=5,
                token=cml_token,
            )
            if golden_points and "error" not in golden_points[0]:
                for g_point in golden_points:
                    g_payload = g_point.get("payload", {})
                    # Scan all payload string values for SQL statements
                    for val in g_payload.values():
                        val_str = str(val)
                        if any(kw in val_str.upper() for kw in ["SELECT", "FROM", "WHERE"]):
                            golden_query_cols.update(extract_sql_columns(val_str, valid_schema_columns))
                if golden_query_cols:
                    break
        except Exception:
            continue

    # 1c. Scan point payloads for embedded Golden Query SQLs
    for point in retrieved_points:
        payload = point.get("payload", {})
        for val in payload.values():
            val_str = str(val)
            if any(kw in val_str.upper() for kw in ["SELECT", "FROM", "WHERE"]):
                golden_query_cols.update(extract_sql_columns(val_str, valid_schema_columns))

    print(f"🔑 [Schema Safeguard] Extracted Golden Query columns to protect: {sorted(list(golden_query_cols))}")

    if not retrieved_tables:
        error_msg = "CRITICAL ERROR: No matching tables found in Qdrant."
        print(f"🚨 {error_msg}")
        return yaml.dump({"database_type": "Cloudera Impala", "error": error_msg}, sort_keys=False)
    
    # Simple word tokenization for user query keyword matching (no regex)
    clean_query = user_query.lower()
    for char in ['?', '!', '.', ',', ':', ';']:
        clean_query = clean_query.replace(char, ' ')
    query_tokens = set(clean_query.split())

    # ==========================================
    # STAGE 2: LEXICAL-BOOSTED PER-TABLE RERANKING
    # ==========================================
    winning_columns = []
    for table in retrieved_tables:
        t_name = table.get("name")
        table_docs = []
        table_mapping = []

        for col in table.get("columns", []):
            c_name = col.get("name", "")
            raw_desc = str(col.get("description", "")).strip()

            # Clean description for matching
            clean_desc = raw_desc
            if "[LLM Context" in clean_desc:
                clean_desc = clean_desc.split("[LLM Context")[0].strip()
            if not clean_desc:
                clean_desc = "No description provided."
            
            c_type = col.get("type", "")

            # Document string evaluated by cross-encoder
            doc_string = f"Column Name: {c_name} | Description: {clean_desc} | Table: {t_name} | Type: {c_type}"
            table_docs.append(doc_string)

            # Count exact token overlaps between query and (Column Name + Clean Description)
            col_search_text = f"{c_name} {clean_desc}".lower()
            for char in ['?', '!', '.', ',', ':', ';', '(', ')', '[', ']']:
                col_search_text = col_search_text.replace(char, ' ')
            col_tokens = set(col_search_text.split())
            token_matches = len(query_tokens.intersection(col_tokens))

            table_mapping.append({
                "table": t_name,
                "column": c_name,
                "matches": token_matches
            })

        if not table_docs:
            continue

        try:
            rerank_results = rerank_documents(
                query=user_query,
                documents=table_docs,
                engine_url=embed_url,
                cml_token=cml_token,
                top_n=len(table_docs),  # Rerank full pool before lexical weighting and top_n filtering
                timeout=15,
            )

            # Apply Lexical Overlap Multiplier to neural scores
            boosted_hits = []
            for hit in rerank_results:
                raw_score = hit.get("score", hit.get("relevance_score", 0.0))
                idx = hit.get("index")

                if idx is not None:
                    matches = table_mapping[idx]["matches"]
                    # Boost score by 50% per matching keyword in column name or description
                    match_multiplier = 1.0 + (0.5 * matches) if matches > 0 else 1.0
                    boosted_score = raw_score * match_multiplier

                    hit_data = table_mapping[idx].copy()
                    hit_data["score"] = boosted_score
                    boosted_hits.append(hit_data)

            # Sort by boosted score and apply top_n cap per table
            boosted_hits.sort(key=lambda x: x["score"], reverse=True)
            top_table_hits = boosted_hits[:top_columns_per_table]

            # Relative thresholding on boosted scores
            max_boosted_score = top_table_hits[0]["score"] if top_table_hits else 0.0
            relative_threshold = max_boosted_score * relative_threshold_ratio

            for col_data in top_table_hits:
                if col_data["score"] >= relative_threshold:
                    col_data["score"] = round(col_data["score"], 4)
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

                # 1. Column passed per-table relative thresholding
                if c_name in col_scores:
                    col["score"] = col_scores[c_name]
                    mandatory_columns.append(col)
                # 2. Structural Schema Safeguards (Primary Keys, Foreign Keys, or Default Time Axis)
                elif (col.get("primary_key") or
                      "references" in col or
                      "DEFAULT_TIME_AXIS: True" in c_desc):
                    mandatory_columns.append(col)
                # 3. Golden Query Safeguard: Preserve columns referenced in Golden Queries
                elif c_name.lower() in golden_query_cols:
                    mandatory_columns.append(col)

            pruned_tables.append(_normalize_table_dict(table, mandatory_columns))

    final_schema = {
        "database_type": "Cloudera Impala",
        "tables": pruned_tables
    }

    return yaml.dump(final_schema, sort_keys=False, default_flow_style=False)


def search_database_schema(user_question: str) -> str:
    # 1. Fetch pure YAML schema context
    raw_schema_context = get_smart_schema_context(user_query=user_question)
    
    # 2. Clean the score fields while it is pure YAML
    # cleaned_schema = clean_schema_yaml(raw_schema_context)
    cleaned_schema = raw_schema_context
    
    # 3. Fetch golden queries and append
    try:
        golden_context = search_golden_queries(user_question=user_question)
        if golden_context and "No verified golden queries found" not in golden_context:
            return f"{cleaned_schema}\n\n{golden_context}"
    except Exception as e:
        print(f"⚠️ Warning: Golden query lookup failed: {e}")
        
    return cleaned_schema