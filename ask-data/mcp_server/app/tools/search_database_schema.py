import os
import re
import yaml
from datetime import datetime, timedelta

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

# 🌟 NEW: Import Enterprise Scoring Module
from shared.search_utils import calculate_unified_score 

from app.tools.search_golden_queries import search_golden_queries

NO_RELEVANT_SCHEMA = "NO_RELEVANT_SCHEMA"
NO_SCHEMA_RESPONSE = "I am sorry, I don't have this information on my database."

def _resolve_relative_date(date_str: str) -> str:
    if not date_str:
        return ""
    clean_str = str(date_str).strip().lower()
    if clean_str.startswith('d-') or clean_str.startswith('d+'):
        try:
            offset = int(clean_str.replace('d', ''))
            base_date = datetime.now()
            target_date = base_date + timedelta(days=offset)
            return target_date.strftime('%Y-%m-%d')
        except ValueError:
            pass
    return str(date_str).strip()

def clean_schema_yaml(raw_yaml_str: str) -> str:
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
    clean_cols = []
    for col in columns:
        clean_col = {}
        if "name" in col: clean_col["name"] = col["name"]
        if "score" in col: clean_col["score"] = col["score"]
        if "type" in col: clean_col["type"] = col["type"]
        if col.get("primary_key") is True: clean_col["primary_key"] = True
        if "references" in col: clean_col["references"] = col["references"]
        if "description" in col: clean_col["description"] = col["description"]
        clean_cols.append(clean_col)

    clean_table = {"name": table.get("name")}
    if "score" in table: clean_table["score"] = table["score"]
    clean_table["description"] = table.get("description")
    
    if "availability_date" in table:
        clean_table["availability_date"] = _resolve_relative_date(table["availability_date"])

    clean_table["columns"] = clean_cols
    return clean_table

def extract_sql_metadata(text: str, valid_tables: set, valid_columns: set) -> tuple[set, set]:
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
                    if stmt is None: continue
                    for tbl in stmt.find_all(exp.Table):
                        if tbl.this:
                            db_part = str(tbl.db).lower().strip('`"') if tbl.db else ""
                            tbl_part = str(tbl.this.name).lower().strip('`"')
                            full_tbl = f"{db_part}.{tbl_part}" if db_part else tbl_part

                            if full_tbl in valid_tables: found_tables.add(full_tbl)
                            elif tbl_part in valid_tables: found_tables.add(tbl_part)

                    for col in stmt.find_all(exp.Column):
                        if col.name:
                            c_name = col.name.lower()
                            if c_name in valid_columns: found_columns.add(c_name)

            if found_tables or found_columns:
                return found_tables, found_columns
        except Exception:
            pass 

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
    top_tables = int(os.getenv("SCHEMA_TOP_TABLES", top_tables))
    top_columns_per_table = int(os.getenv("SCHEMA_TOP_COLUMNS_PER_TABLE", top_columns_per_table))
    relative_threshold_ratio = float(os.getenv("SCHEMA_RELATIVE_THRESHOLD_RATIO", relative_threshold_ratio))
    absolute_min_score = float(os.getenv("SCHEMA_ABSOLUTE_MIN_SCORE", absolute_min_score))
    global_table_threshold_ratio = float(os.getenv("SCHEMA_GLOBAL_TABLE_THRESHOLD_RATIO", global_table_threshold_ratio))

    cml_token = get_cml_token()
    embed_url = os.getenv("EMBED_RERANK_URL", "").rstrip("/")
    vectordb_url = os.getenv("VECTORDB_SERVER_URL", "").rstrip("/")
    schema_collection = os.getenv("SCHEMA_COLLECTION", "bni_schema_definitions")

    try:
        query_vector = get_embedding_vector(user_query, engine_url=embed_url, cml_token=cml_token, timeout=15)
        qdrant_client = QdrantClient(base_url=vectordb_url, token=cml_token)
        retrieved_points = qdrant_client.search(schema_collection, query_vector, top_k=top_tables, token=cml_token)
        if retrieved_points and "error" in retrieved_points[0]:
            raise RuntimeError(retrieved_points[0]["error"])
    except Exception as e:
        return yaml.dump({"database_type": "Cloudera Impala", "error": f"CRITICAL ERROR: {e}"}, sort_keys=False), ""

    retrieved_tables = []
    valid_schema_tables = set()
    valid_schema_columns = set()
    golden_query_tables = set()
    golden_query_cols = set()

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

    golden_context = ""
    try:
        golden_context = search_golden_queries(user_question=user_query)
        if golden_context and "No verified golden queries found" not in golden_context:
            g_tables, g_cols = extract_sql_metadata(golden_context, valid_schema_tables, valid_schema_columns)
            golden_query_tables.update(g_tables)
            golden_query_cols.update(g_cols)
    except Exception as e:
        print(f"⚠️ Golden Query extraction warning: {e}")

    for point in retrieved_points:
        payload = point.get("payload", {})
        for val in payload.values():
            val_str = str(val)
            if any(kw in val_str.upper() for kw in ["SELECT", "FROM", "WHERE"]):
                g_tables, g_cols = extract_sql_metadata(val_str, valid_schema_tables, valid_schema_columns)
                golden_query_tables.update(g_tables)
                golden_query_cols.update(g_cols)

    if not retrieved_tables:
        return yaml.dump({"database_type": "Cloudera Impala", "tables": [], "error": NO_RELEVANT_SCHEMA}, sort_keys=False), golden_context

    # ==========================================
    # STAGE 2 & 3: DESCRIPTION-ONLY RERANKING & UNIFIED SCORING
    # ==========================================
    winning_columns = []
    for table in retrieved_tables:
        t_name = table.get("name")
        table_vector_score = table.get("score", 0.0)
        table_docs = []
        table_mapping = []

        for col in table.get("columns", []):
            c_name = col.get("name", "")
            raw_desc = str(col.get("description", "")).strip()
            
            # 🌟 STRICT DESCRIPTION ONLY
            clean_desc = raw_desc if raw_desc else "No description provided."
            table_docs.append(clean_desc)

            table_mapping.append({
                "table": t_name,
                "column": c_name,
                "description": clean_desc,
                "vector_score": table_vector_score
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
                raw_rerank_score = hit.get("score", hit.get("relevance_score", 0.0))
                idx = hit.get("index")

                if idx is not None:
                    col_meta = table_mapping[idx]
                    
                    # 🌟 ENTERPRISE SCORE FUSION (0.0 to 1.0)
                    final_score = calculate_unified_score(
                        raw_vector_score=col_meta["vector_score"],
                        raw_rerank_score=raw_rerank_score,
                        description=col_meta["description"],
                        user_query=user_query
                    )

                    hit_data = col_meta.copy()
                    hit_data["score"] = final_score
                    boosted_hits.append(hit_data)

            boosted_hits.sort(key=lambda x: x["score"], reverse=True)
            top_table_hits = boosted_hits[:top_columns_per_table]

            max_boosted_score = top_table_hits[0]["score"] if top_table_hits else 0.0
            relative_threshold = max(max_boosted_score * relative_threshold_ratio, absolute_min_score)

            for col_data in top_table_hits:
                if col_data["score"] >= relative_threshold:
                    winning_columns.append(col_data)

        except Exception as e:
            print(f"⚠️ Per-table reranking failed for {t_name}: {e}")

    # STAGE 4: GLOBAL PRUNING 
    global_max_score = max([item['score'] for item in winning_columns], default=0.0)
    strong_table_names = {item['table'] for item in winning_columns if item['score'] >= (global_max_score * global_table_threshold_ratio)}
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

                if c_name in col_scores:
                    col["score"] = col_scores[c_name]
                    mandatory_columns.append(col)
                elif col.get("primary_key") or "references" in col or "DEFAULT_TIME_AXIS: True" in c_desc:
                    mandatory_columns.append(col)
                elif c_name.lower() in golden_query_cols and table_name.lower() in golden_query_tables:
                    mandatory_columns.append(col)

            mandatory_columns.sort(key=lambda c: c.get("score", 0.0) or 0.0, reverse=True)
            pruned_tables.append(_normalize_table_dict(table, mandatory_columns))

    pruned_tables.sort(key=lambda tbl: tbl.get("score", 0.0) or 0.0, reverse=True)

    if not pruned_tables:
        return yaml.dump({"database_type": "Cloudera Impala", "tables": [], "error": NO_RELEVANT_SCHEMA}, sort_keys=False), golden_context

    final_schema = {"database_type": "Cloudera Impala", "tables": pruned_tables}
    return yaml.dump(final_schema, sort_keys=False, default_flow_style=False), golden_context

def _has_no_tables(schema_context: str) -> bool:
    if NO_RELEVANT_SCHEMA in schema_context: return True
    try:
        data = yaml.safe_load(schema_context)
        tables = data.get("tables")
        return isinstance(tables, list) and len(tables) == 0
    except Exception:
        return False

def search_database_schema(user_question: str) -> str:
    raw_schema_context, golden_context = get_smart_schema_context_with_golden(user_query=user_question)
    raw_schema_context = clean_schema_yaml(raw_schema_context)

    if _has_no_tables(raw_schema_context):
        return NO_SCHEMA_RESPONSE

    if golden_context and "No verified golden queries found" not in golden_context:
        return f"{raw_schema_context}\n\n{golden_context}"

    return raw_schema_context