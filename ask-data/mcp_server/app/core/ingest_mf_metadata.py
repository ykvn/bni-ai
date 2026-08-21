"""
MetricFlow (mf) metadata ingestion from Local YAML Schema.

Reads bni_dbt_schema.yaml directly, parses metrics, dimensions, entities, 
resolves default time dimensions and availability dates, and indexes them into Qdrant.
"""
import os
import json
import yaml
from pathlib import Path
from datetime import datetime, timedelta

from app.core.ingest_common import bootstrap_env, reset_and_index

# Standardized project-root bootstrap (loads .env)
bootstrap_env()

def _resolve_relative_date(date_str: str) -> str:
    """Parses 'd-1', 'D-2' etc. into a real YYYY-MM-DD string based on current date."""
    if not date_str:
        return ""
    clean_str = str(date_str).strip().lower()
    if clean_str.startswith('d-') or clean_str.startswith('d+'):
        try:
            offset = int(clean_str.replace('d', ''))
            target_date = datetime.now() + timedelta(days=offset)
            return target_date.strftime('%Y-%m-%d')
        except ValueError:
            pass
    return str(date_str).strip()

def get_yaml_path() -> Path:
    """Resolves the path to the generated dbt schema YAML."""
    ask_data_root = Path("/home/cdsw/ask-data")
    return ask_data_root / "dbt_service" / "dbt_project" / "models" / "bni_dbt_schema.yaml"

def ingest_mf_schema(
    api_url: str = None, # Left for backward compatibility, but unused
    vectordb_server_url: str = None,
    embed_rerank_url: str = None,
    collection_name: str = None,
    cml_token: str = None,
):
    """Parses local bni_dbt_schema.yaml and indexes enriched payloads into Vector DB."""
    yaml_path = get_yaml_path()
    
    if not yaml_path.exists():
        print(f"❌ Error: Schema YAML not found at {yaml_path}. Aborting ingestion.", flush=True)
        return

    print(f"🌐 Loading local MetricFlow schema from: {yaml_path}...", flush=True)
    
    with open(yaml_path, "r") as f:
        schema = yaml.safe_load(f)

    metrics = schema.get("metrics", [])
    semantic_models = schema.get("semantic_models", [])

    catalog_texts = []
    metadatas = []

    # 1. Build lookup maps from Semantic Models
    sm_primary_entity = {}
    measure_to_time_dim = {}
    measure_to_sm_name = {}
    sm_avail_date = {}

    for sm in semantic_models:
        sm_name = sm.get("name")
        primary_entity = sm_name # Fallback
        raw_avail_date = sm.get("availability_date", "")
        resolved_avail_date = _resolve_relative_date(raw_avail_date) if raw_avail_date else ""
        sm_avail_date[sm_name] = resolved_avail_date
        
        # Find Primary Entity
        for ent in sm.get("entities", []):
            if ent.get("type") == "primary":
                primary_entity = ent.get("name")
        sm_primary_entity[sm_name] = primary_entity

        # Map Measures -> Time Dimension & Semantic Model
        for m in sm.get("measures", []):
            m_name = m.get("name")
            agg_time_col = m.get("agg_time_dimension")
            if m_name:
                measure_to_sm_name[m_name] = sm_name
                if agg_time_col:
                    measure_to_time_dim[m_name] = f"{primary_entity}__{agg_time_col}"

        # 2. Process Dimensions inside the Semantic Model
        for d in sm.get("dimensions", []):
            d_name = d.get("name")
            d_type = d.get("type", "categorical")
            d_desc = d.get("description", "No description provided.")
            
            group_by_path = f"{primary_entity}__{d_name}"
            
            searchable_text = (
                f"Dimension Path (Group By): {group_by_path}\n"
                f"Data Type: {d_type}\n"
                f"Description: {d_desc}"
            )
            if resolved_avail_date:
                searchable_text += f"\nAvailability Date: {resolved_avail_date}"

            structured_payload = {
                "item_type": "dimension",
                "name": group_by_path,
                "raw_name": f"{sm_name}__{d_name}",
                "data_type": d_type,
                "description": d_desc
            }
            if resolved_avail_date:
                structured_payload["availability_date"] = resolved_avail_date

            catalog_texts.append(searchable_text)
            metadatas.append({
                "item_type": "dimension",
                "name": group_by_path,
                "raw_json": json.dumps(structured_payload, indent=2),
            })

        # 3. Process Entities inside the Semantic Model
        for e in sm.get("entities", []):
            e_name = e.get("name")
            e_type = e.get("type", "unknown")
            e_expr = e.get("expr", e_name)

            searchable_text = (
                f"Entity Key: {e_name}\n"
                f"Key Type: {e_type}\n"
                f"Semantic Model / Table: {sm_name}\n"
                f"Expression: {e_expr}"
            )

            structured_payload = {
                "item_type": "entity",
                "name": e_name,
                "type": e_type,
                "semantic_model": sm_name,
                "expr": e_expr
            }

            catalog_texts.append(searchable_text)
            metadatas.append({
                "item_type": "entity",
                "name": e_name,
                "raw_json": json.dumps(structured_payload, indent=2),
            })

    # 4. Process Top-Level Metrics
    for m in metrics:
        m_name = m.get("name", "unknown")
        m_label = m.get("label", m_name)
        m_desc = m.get("description", "No description provided.")
        
        measure_ref = m.get("type_params", {}).get("measure")
        default_time_dim = measure_to_time_dim.get(measure_ref, "None")
        
        m_sm_name = measure_to_sm_name.get(measure_ref)
        m_avail_date = sm_avail_date.get(m_sm_name, "")

        searchable_text = (
            f"Metric Name: {m_name}\n"
            f"Label: {m_label}\n"
            f"Description: {m_desc}\n"
            f"Default Time Dimension: {default_time_dim}"
        )
        if m_avail_date:
            searchable_text += f"\nAvailability Date: {m_avail_date}"

        structured_payload = {
            "item_type": "metric",
            "name": m_name,
            "label": m_label,
            "description": m_desc,
            "default_time_dimension": default_time_dim
        }
        if m_avail_date:
            structured_payload["availability_date"] = m_avail_date

        catalog_texts.append(searchable_text)
        metadatas.append({
            "item_type": "metric",
            "name": m_name,
            "raw_json": json.dumps(structured_payload, indent=2),
        })

    print(f"📊 Extracted Total Chunks directly from YAML: {len(metrics)} Metrics, {len(catalog_texts) - len(metrics)} Dims/Entities", flush=True)

    # 5. Index chunks into Qdrant
    reset_and_index(
        collection_name=collection_name,
        documents=catalog_texts,
        metadatas=metadatas,
        vectordb_server_url=vectordb_server_url,
        embed_rerank_url=embed_rerank_url,
        cml_token=cml_token,
        dataset_name="MetricFlow Catalog (YAML-Based)",
    )