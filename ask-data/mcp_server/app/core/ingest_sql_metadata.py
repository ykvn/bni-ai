"""
SQL metadata ingestion: golden queries (JSON) + DB schema (YAML).

Uses the shared ``ingest_common`` bootstrap and ``reset_and_index`` routine
so this pipeline behaves identically to the Cube and knowledge pipelines.
"""
import json
import os
import yaml

from app.core.ingest_common import bootstrap_env, reset_and_index, resolve_data_path

# Standardized project-root bootstrap (idempotent, shared across all pipelines)
bootstrap_env()


def ingest_golden_queries(
    json_path: str,
    vectordb_server_url: str,
    embed_rerank_url: str,
    collection_name: str,
    cml_token: str,
):
    """Embeds user intents and stores the verified SQL templates in Qdrant."""
    if not os.path.exists(json_path):
        print(f"⚠️ Golden queries file not found at {json_path}")
        return

    print(f"📖 Reading Golden Queries from {json_path}...")
    with open(json_path, "r", encoding="utf-8") as f:
        queries = json.load(f)

    if not queries:
        return

    # We embed the natural language intent so it matches the user's question semantically
    intents = [
        f"{q.get('user_intent', '')} - {q.get('description', '')}".strip(" -")
        for q in queries
    ]

    metadatas = [
        {
            "user_intent": q.get("user_intent", ""),
            "description": q.get("description", ""),  # 🌟 NEW: Store description in Qdrant metadata
            "sql_template": q.get("sql_template", ""),
            "complexity": q.get("complexity", "unknown"),
            "data_type": "golden_query",
        }
        for q in queries
    ]

    reset_and_index(
        collection_name=collection_name,
        documents=intents,
        metadatas=metadatas,
        vectordb_server_url=vectordb_server_url,
        embed_rerank_url=embed_rerank_url,
        cml_token=cml_token,
        dataset_name="Golden Queries",
    )


def ingest_schema(
    yaml_path: str,
    vectordb_server_url: str,
    embed_rerank_url: str,
    collection_name: str,
    cml_token: str,
):
    """Parses database schema YAML and chunks it by table for vector search."""
    if not os.path.exists(yaml_path):
        print(f"⚠️ Schema file not found at {yaml_path}")
        return

    print(f"📖 Reading Schema from {yaml_path}...")
    with open(yaml_path, "r", encoding="utf-8") as f:
        schema = yaml.safe_load(f)

    tables = schema.get("tables", [])
    if not tables:
        return

    table_texts = []
    metadatas = []

    # Chunk by table to keep context windows small and precise
    for table in tables:
        table_name = table.get("name", "unknown")
        desc = table.get("description", "")
        avail_date = table.get("availability_date", "")

        # Build search-optimized string containing column names and descriptions
        col_details = []
        clean_columns = []
        for c in table.get("columns", []):
            c_name = c.get("name", "")
            c_desc = c.get("description", "")
            col_details.append(f"{c_name} ({c_desc})" if c_desc else c_name)

            clean_col = {"name": c_name}
            if "type" in c:
                clean_col["type"] = c.get("type")
            if c.get("primary_key"):
                clean_col["primary_key"] = True
            if "references" in c:
                clean_col["references"] = c.get("references")
            if "description" in c:
                clean_col["description"] = c.get("description")
            clean_columns.append(clean_col)

        cols_formatted = ", ".join(col_details)
        
        # Inject availability date into the searchable text chunk for the vector model
        searchable_text = f"Table: {table_name}\nDescription: {desc}\n"
        if avail_date:
            searchable_text += f"Availability Date: {avail_date}\n"
        searchable_text += f"Columns: {cols_formatted}"

        clean_table = {
            "name": table_name,
            "description": desc,
        }
        # Ensure availability date stays in the clean payload for LLM Context
        if avail_date:
            clean_table["availability_date"] = avail_date
            
        clean_table["columns"] = clean_columns

        metadatas.append({
            "table_name": table_name,
            "raw_yaml": yaml.dump(clean_table, sort_keys=False, default_flow_style=False),
            "data_type": "schema_table",
        })

    reset_and_index(
        collection_name=collection_name,
        documents=table_texts,
        metadatas=metadatas,
        vectordb_server_url=vectordb_server_url,
        embed_rerank_url=embed_rerank_url,
        cml_token=cml_token,
        dataset_name="Schema Tables",
    )