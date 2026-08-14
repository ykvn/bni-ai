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
    """Parses MetricFlow API metadata (metrics, dimensions, entities) and indexes it into Vector DB."""
    if not api_url:
        api_url = get_default_api_url()

    schema = fetch_mf_metadata(api_url, cml_token)
    if not schema or not isinstance(schema, dict):
        print("⚠️ Invalid or empty metadata retrieved from API. Aborting ingestion.", flush=True)
        return

    catalog_texts = []
    metadatas = []

    # 1. Process Metrics
    metrics = schema.get("metrics", [])
    for m in metrics:
        m_name = m.get("name", "unknown")
        m_label = m.get("label", m_name)
        m_desc = m.get("description", "No description provided.")
        m_syns = m.get("synonyms", [])

        searchable_text = (
            f"Metric Name: {m_name}\n"
            f"Label: {m_label}\n"
            f"Description: {m_desc}\n"
            f"Synonyms: {', '.join(m_syns) if m_syns else 'None'}"
        )

        structured_payload = {
            "item_type": "metric",
            "name": m_name,
            "label": m_label,
            "description": m_desc,
            "synonyms": m_syns
        }

        catalog_texts.append(searchable_text)
        metadatas.append({
            "item_type": "metric",
            "name": m_name,
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