import os
import re
import yaml

try:
    import sqlglot
    from sqlglot import exp
    SQLGLOT_AVAILABLE = True
except ImportError:
    SQLGLOT_AVAILABLE = False
    print("⚠️ sqlglot not installed. Falling back to basic word intersection for Golden Query table/column extraction.")

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


def extract_sql_metadata(text: str, valid_tables: set, valid_columns: set) -> tuple[set, set]:
    """Extracts qualified table names and column names referenced in Golden Queries."""
    found_tables = set()
    found_columns = set()

    if SQLGLOT_AVAILABLE:
        try:
            if "SQL:" in text:
                sql_blocks = re.split(r"(?is)\s*SQL:\s*", text)[1:]
            else:
                sql_blocks = [text]

            for block in sql_blocks:
                block = re.split(r"(?is)\s*--\s*Example\b", block)[0]
                for stmt in sqlglot.parse(block, read="impala"):
                    if stmt is None:
                        continue

                    # Extract Table nodes (handles schema.table and aliases)
                    for tbl in stmt.find_all(exp.Table):
                        if tbl.this:
                            db_part = str(tbl.db).lower().strip('`"') if tbl.db else ""
                            tbl_part = str(tbl.this.name).lower().strip('`"')
                            full_tbl = f"{db_part}.{tbl_part}" if db_part else tbl_part

                            if full_tbl in valid_tables:
                                found_tables.add(full_tbl)
                            elif tbl_part in valid_tables:
                                found_tables.add(tbl_part)

                    # Extract Column nodes
                    for col in stmt.find_all(exp.Column):
                        if col.name:
                            c_name = col.name.lower()
                            if c_name in valid_columns:
                                found_columns.add(c_name)

            if found_tables or found_columns:
                return found_tables, found_columns
        except Exception:
            pass  # Fallback if AST parsing fails

    # Fallback: String splitting without regex
    text_lower = text.lower()
    for char in ['(', ')', ',', '=', '<', '>', '!', "'", '"', '`', ';', ':', '?', '\n', '\t']:
        text_lower = text_lower.replace(char, ' ')

    words = set(text_lower.split())
    found_tables = words.intersection(valid_tables)
    found_columns = words.intersection(valid_columns)

    return found_tables, found_columns


def get_smart_schema_context_with_golden(
    user_query: str,
    top_tables: int = 5,
    top_columns_per_table: int = 10,
    relative_threshold_ratio: float = 0.05,
    absolute_min_score: float = 0.001,
    global_table_threshold_ratio: float = 0.30
) -> tuple[str, str]:
    """Retrieves schema context and golden queries with per-column and global per-table pruning."""
    cml_token = get_cml_token()
    embed_url = os.getenv("EMBED_RERANK_URL", "").rstrip("/")
    vectordb_url = os.getenv("VECTORDB_SERVER_URL", "").rstrip("/")
    schema_collection = os.getenv("SCHEMA_COLLECTION", "bni_schema_definitions")

    # ==========================================
    # STAGE 1: VECTOR SEARCH (Find Tables & Golden Queries)
    # ==========================================
    try:
        query_vector = get_embedding_vector(user_query, engine_url=embed_url, cml_token=cml_token, timeout=15)
    except Exception as e:
        error_msg = f"CRITICAL ERROR: Embedding API failed at {embed_url}: {e}"
        print(f"🚨 {error_msg}")
        return yaml.dump({"database_type": "Cloudera Impala", "error": error_msg}, sort_keys=False), ""

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
        return yaml.dump({"database_type": "Cloudera Impala", "error": error_msg}, sort_keys=False), ""

    retrieved_tables = []
    valid_schema_tables = set()
    valid_schema_columns = set()
    golden_query_tables = set()
    golden_query_cols = set()

    # 1a. Build retrieved_tables and collect all valid table/column names first
    for point in retrieved_points:
        payload = point.get("payload", {})
        point_score = point.get("score")
        raw_yaml_str = payload.get("raw_yaml")

        if raw_yaml_str:
            parsed_table = yaml.safe_load(raw_yaml_str)
            if point_score is not None:
                parsed_table["score"] = round(point_score, 4)
            retrieved_tables.append(parsed_table)
            
            if "name" in parsed_table:
                valid_schema_tables.add(str(parsed_table["name"]).lower())

            for col in parsed_table.get("columns", []):
                if "name" in col:
                    valid_schema_columns.add(str(col["name"]).lower())

    # 1b. Fetch Golden Queries via search_golden_queries tool BEFORE pruning
    golden_context = ""
    try:
        golden_context = search_golden_queries(user_question=user_query)
        if golden_context and "No verified golden queries found" not in golden_context:
            g_tables, g_cols = extract_sql_metadata(golden_context, valid_schema_tables, valid_schema_columns)
            golden_query_tables.update(g_tables)
            golden_query_cols.update(g_cols)
    except Exception as e:
        print(f"⚠️ Golden Query extraction warning: {e}")

    # 1c. Scan point payloads for embedded Golden Query SQLs
    for point in retrieved_points:
        payload = point.get("payload", {})
        for val in payload.values():
            val_str = str(val)
            if any(kw in val_str.upper() for kw in ["SELECT", "FROM", "WHERE"]):
                g_tables, g_cols = extract_sql_metadata(val_str, valid_schema_tables, valid_schema_columns)
                golden_query_tables.update(g_tables)
                golden_query_cols.update(g_cols)

    print(f"🔑 [Schema Safeguard] Golden Query Protected Tables: {sorted(list(golden_query_tables))} | Columns: {sorted(list(golden_query_cols))}")

    if not retrieved_tables:
        error_msg = "CRITICAL ERROR: No matching tables found in Qdrant."
        print(f"🚨 {error_msg}")
        return yaml.dump({"database_type": "Cloudera Impala", "error": error_msg}, sort_keys=False), golden_context
    
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

            clean_desc = raw_desc
            if "[LLM Context" in clean_desc:
                clean_desc = clean_desc.split("[LLM Context")[0].strip()
            if not clean_desc:
                clean_desc = "No description provided."
            
            c_type = col.get("type", "")

            doc_string = f"Column Name: {c_name} | Description: {clean_desc} | Table: {t_name} | Type: {c_type}"
            table_docs.append(doc_string)

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
                top_n=len(table_docs),
                timeout=15,
            )

            boosted_hits = []
            for hit in rerank_results:
                raw_score = hit.get("score", hit.get("relevance_score", 0.0))
                idx = hit.get("index")

                if idx is not None:
                    matches = table_mapping[idx]["matches"]
                    match_multiplier = 1.0 + (0.5 * matches) if matches > 0 else 1.0
                    boosted_score = raw_score * match_multiplier

                    hit_data = table_mapping[idx].copy()
                    hit_data["score"] = boosted_score
                    boosted_hits.append(hit_data)

            boosted_hits.sort(key=lambda x: x["score"], reverse=True)
            top_table_hits = boosted_hits[:top_columns_per_table]

            max_boosted_score = top_table_hits[0]["score"] if top_table_hits else 0.0
            
            # Enforce absolute score floor to prevent micro-scores
            relative_threshold = max(max_boosted_score * relative_threshold_ratio, absolute_min_score)

            for col_data in top_table_hits:
                if col_data["score"] >= relative_threshold:
                    col_data["score"] = round(col_data["score"], 4)
                    winning_columns.append(col_data)

        except Exception as e:
            print(f"⚠️ Per-table reranking failed for {t_name}: {e}")

    # ==========================================
    # STAGE 3: GLOBAL TABLE PRUNING & SCHEMA RECONSTRUCTION
    # ==========================================
    # 1. Compute global max score across all candidate column hits
    global_max_score = max([item['score'] for item in winning_columns], default=0.0)

    # 2. Filter tables that meet at least 15% of the global max score
    strong_table_names = {
        item['table'] for item in winning_columns 
        if item['score'] >= (global_max_score * global_table_threshold_ratio)
    }

    # 3. Union strong tables with tables explicitly protected by Golden Queries
    relevant_table_names = strong_table_names.union(golden_query_tables)
    pruned_tables = []

    for table in retrieved_tables:
        table_name = table.get("name")
        if table_name in relevant_table_names:
            col_scores = {item['column']: item['score'] for item in winning_columns if item['table'] == table_name}

            mandatory_columns = []
            for col in table.get("columns", []):
                c_name = col.get("name", "")
                c_desc = str(col.get("description", ""))

                # A. Column passed per-table relative thresholding & absolute floor
                if c_name in col_scores:
                    col["score"] = col_scores[c_name]
                    mandatory_columns.append(col)
                # B. Structural Schema Safeguards (PK, FK, or DEFAULT_TIME_AXIS)
                elif (col.get("primary_key") or
                      "references" in col or
                      "DEFAULT_TIME_AXIS: True" in c_desc):
                    mandatory_columns.append(col)
                # C. Golden Query Safeguard (Protected within referenced Golden Query tables)
                elif c_name.lower() in golden_query_cols and table_name.lower() in golden_query_tables:
                    mandatory_columns.append(col)

            # ORDER BY: Sort columns by score DESC
            mandatory_columns.sort(key=lambda c: c.get("score", 0.0) or 0.0, reverse=True)

            pruned_tables.append(_normalize_table_dict(table, mandatory_columns))

    # ORDER BY: Sort tables by vector score DESC
    pruned_tables.sort(key=lambda tbl: tbl.get("score", 0.0) or 0.0, reverse=True)

    final_schema = {
        "database_type": "Cloudera Impala",
        "tables": pruned_tables
    }

    return yaml.dump(final_schema, sort_keys=False, default_flow_style=False), golden_context


def get_smart_schema_context(
    user_query: str,
    top_tables: int = 5,
    top_columns_per_table: int = 10,
    relative_threshold_ratio: float = 0.05,
    absolute_min_score: float = 0.001,
    global_table_threshold_ratio: float = 0.15
) -> str:
    schema_yaml, _ = get_smart_schema_context_with_golden(
        user_query=user_query,
        top_tables=top_tables,
        top_columns_per_table=top_columns_per_table,
        relative_threshold_ratio=relative_threshold_ratio,
        absolute_min_score=absolute_min_score,
        global_table_threshold_ratio=global_table_threshold_ratio
    )
    return schema_yaml


def search_database_schema(user_question: str) -> str:
    raw_schema_context, golden_context = get_smart_schema_context_with_golden(user_query=user_question)
    
    if golden_context and "No verified golden queries found" not in golden_context:
        return f"{raw_schema_context}\n\n{golden_context}"
        
    return raw_schema_context