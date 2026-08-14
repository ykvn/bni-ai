"""
MetricFlow (mf) metadata ingestion from REST API endpoint.

Fetches metadata from DBT_METRICFLOW_URL + '/api/v1/meta',
parses metrics, dimensions, and entities, and indexes them into Qdrant vector database.
"""
import os
import json
import httpx

from shared.cml_auth import build_cml_headers
from app.core.ingest_common import bootstrap_env, reset_and_index

# Standardized project-root bootstrap (loads .env)
bootstrap_env()

def get_default_api_url() -> str:
    base_url = os.getenv("DBT_METRICFLOW_URL", "https://dbt.cai.apps.dataservices.bni.co.id")
    return f"{base_url.rstrip('/')}/api/v1/meta"


def fetch_mf_metadata(api_url: str = None, cml_token: str = None) -> dict:
    """Fetches dbt MetricFlow metadata JSON from the REST API endpoint with Bearer authentication."""
    if not api_url:
        api_url = get_default_api_url()

    print(f"🌐 Fetching MetricFlow metadata from API: {api_url}...", flush=True)
    
    # Build authentication headers using CML token or fallback to environment
    token = cml_token or os.getenv("CML_TOKEN") or os.getenv("LITELLM_API_KEY")
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    # Merge with standard CML headers if build_cml_headers exists
    try:
        headers.update(build_cml_headers(token))
    except Exception:
        pass

    try:
        with httpx.Client(verify=False, timeout=30.0) as client:
            response = client.get(api_url, headers=headers)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        print(f"❌ Error fetching metadata from {api_url}: {e}", flush=True)
        return {}


def ingest_mf_schema(
    api_url: str = None,
    vectordb_server_url: str = None,
    embed_rerank_url: str = None,
    collection_name: str = None,
    cml_token: str = None,
):
    schema = fetch_mf_metadata(api_url, cml_token)
    if not schema or not isinstance(schema, dict):
        return

    catalog_texts = []
    metadatas = []

    # 1. Build a lookup map of semantic_model -> primary_entity_name
    # Example: "cai_customers" -> "customer_id", "cai_savings" -> "savings_id"
    model_to_primary_entity = {}
    for entity in schema.get("entities", []):
        if entity.get("type") == "primary":
            model_to_primary_entity[entity.get("semantic_model")] = entity.get("name")

    # 2. Process Metrics
    for m in schema.get("metrics", []):
        # ... (Metric processing remains unchanged)
        pass

    # 3. Process Dimensions & Compute Valid Group-By Paths
    for d in schema.get("dimensions", []):
        d_name = d.get("name", "unknown")  # e.g., "cai_customers__bank_name"
        d_desc = d.get("description", "No description provided.")
        d_meta = d.get("meta", {})

        # Extract semantic model name and column name
        group_by_path = d_name
        if "__" in d_name:
            parts = d_name.split("__", 1)
            model_prefix, col_name = parts[0], parts[1]
            
            # If the model has a primary entity, create the valid MetricFlow join path
            if model_prefix in model_to_primary_entity:
                primary_entity = model_to_primary_entity[model_prefix]
                group_by_path = f"{primary_entity}__{col_name}"  # e.g., "customer_id__bank_name"

        searchable_text = (
            f"Dimension Path (Group By): {group_by_path}\n"
            f"Raw Metadata Name: {d_name}\n"
            f"Description: {d_desc}"
        )

        structured_payload = {
            "item_type": "dimension",
            "name": group_by_path,  # Now provides 'customer_id__bank_name' directly to the LLM
            "raw_name": d_name,
            "description": d_desc,
            "meta": d_meta
        }

        catalog_texts.append(searchable_text)
        metadatas.append({
            "item_type": "dimension",
            "name": group_by_path,
            "raw_json": json.dumps(structured_payload, indent=2),
        })

    # 2. Process Dimensions
    dimensions = schema.get("dimensions", [])
    for d in dimensions:
        d_name = d.get("name", "unknown")
        d_desc = d.get("description", "No description provided.")
        d_meta = d.get("meta", {})

        searchable_text = (
            f"Dimension Path (Group By): {d_name}\n"
            f"Description: {d_desc}"
        )

        structured_payload = {
            "item_type": "dimension",
            "name": d_name,
            "description": d_desc,
            "meta": d_meta
        }

        catalog_texts.append(searchable_text)
        metadatas.append({
            "item_type": "dimension",
            "name": d_name,
            "raw_json": json.dumps(structured_payload, indent=2),
        })

    # 3. Process Entities
    entities = schema.get("entities", [])
    for e in entities:
        e_name = e.get("name", "unknown")
        e_type = e.get("type", "unknown")
        e_model = e.get("semantic_model", "unknown")
        e_expr = e.get("expr", e_name)

        searchable_text = (
            f"Entity Key: {e_name}\n"
            f"Key Type: {e_type}\n"
            f"Semantic Model / Table: {e_model}\n"
            f"Expression: {e_expr}"
        )

        structured_payload = {
            "item_type": "entity",
            "name": e_name,
            "type": e_type,
            "semantic_model": e_model,
            "expr": e_expr
        }

        catalog_texts.append(searchable_text)
        metadatas.append({
            "item_type": "entity",
            "name": e_name,
            "raw_json": json.dumps(structured_payload, indent=2),
        })

    print(f"📊 Extracted Total Chunks: {len(metrics)} Metrics, {len(dimensions)} Dimensions, {len(entities)} Entities", flush=True)

    if not catalog_texts:
        print("⚠️ No metadata items found to index.", flush=True)
        return

    # 4. Index Chunks into Qdrant
    reset_and_index(
        collection_name=collection_name,
        documents=catalog_texts,
        metadatas=metadatas,
        vectordb_server_url=vectordb_server_url,
        embed_rerank_url=embed_rerank_url,
        cml_token=cml_token,
        dataset_name="MetricFlow Catalog API",
    )