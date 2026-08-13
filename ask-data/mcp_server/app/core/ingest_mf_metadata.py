"""
MetricFlow (mf) metadata ingestion.

Uses the shared ``ingest_common`` bootstrap and ``reset_and_index`` routine
"""
import os
import yaml

from app.core.ingest_common import bootstrap_env, reset_and_index

# Standardized project-root bootstrap
bootstrap_env()

def ingest_mf_schema(
    yaml_path: str,
    vectordb_server_url: str,
    embed_rerank_url: str,
    collection_name: str,
    cml_token: str,
):
    """Parses MetricFlow schema YAML and chunks it by models and metrics for vector search."""
    if not os.path.exists(yaml_path):
        print(f"⚠️ MetricFlow Schema file not found at {yaml_path}", flush=True)
        return

    print(f"📖 Reading MetricFlow Catalog from {yaml_path}...", flush=True)
    with open(yaml_path, "r", encoding="utf-8") as f:
        schema = yaml.safe_load(f)

    catalog_texts = []
    metadatas = []

    # 1. Chunk Semantic Models (Contains Entities and Dimensions)
    for sm in schema.get("semantic_models", []):
        model_name = sm.get("name", "unknown")
        desc = sm.get("description", "")
        
        ent_details = [e.get("name", "") for e in sm.get("entities", [])]
        dim_details = []
        for d in sm.get("dimensions", []):
            d_name = d.get("name", "")
            d_desc = d.get("description", "")
            dim_details.append(f"{d_name} ({d_desc})" if d_desc else d_name)
            
        searchable_text = (
            f"Semantic Model: {model_name}\n"
            f"Description: {desc}\n"
            f"Entities (Keys): {', '.join(ent_details)}\n"
            f"Dimensions (Group By): {', '.join(dim_details)}"
        )
        catalog_texts.append(searchable_text)
        metadatas.append({
            "item_type": "semantic_model",
            "name": model_name,
            "raw_yaml": yaml.dump(sm, sort_keys=False, default_flow_style=False),
        })

    # 2. Chunk Metrics
    for m in schema.get("metrics", []):
        m_name = m.get("name", "unknown")
        m_label = m.get("label", "")
        m_desc = m.get("description", "")
        
        searchable_text = (
            f"Metric: {m_name}\n"
            f"Label: {m_label}\n"
            f"Description: {m_desc}"
        )
        catalog_texts.append(searchable_text)
        metadatas.append({
            "item_type": "metric",
            "name": m_name,
            "raw_yaml": yaml.dump(m, sort_keys=False, default_flow_style=False),
        })

    if not catalog_texts:
        return

    reset_and_index(
        collection_name=collection_name,
        documents=catalog_texts,
        metadatas=metadatas,
        vectordb_server_url=vectordb_server_url,
        embed_rerank_url=embed_rerank_url,
        cml_token=cml_token,
        dataset_name="MetricFlow Catalog",
    )