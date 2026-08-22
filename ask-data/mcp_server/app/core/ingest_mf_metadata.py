"""
MetricFlow (mf) metadata ingestion from Local YAML Schema + Excel Definitions.

Reads bni_dbt_schema.yaml + bni_dbt_definitions.xlsx, parses metrics, dimensions, entities, 
resolves default time dimensions and availability dates, and indexes them into Qdrant.
"""
import os
import json
import yaml
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

from app.core.ingest_common import bootstrap_env, reset_and_index

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

def get_paths():
    ask_data_root = Path("/home/cdsw/ask-data")
    yaml_path = ask_data_root / "dbt_service" / "dbt_project" / "models" / "bni_dbt_schema.yaml"
    excel_path = ask_data_root / "data" / "bni_dbt_definitions.xlsx"
    return yaml_path, excel_path

def ingest_mf_schema(
    api_url: str = None,
    vectordb_server_url: str = None,
    embed_rerank_url: str = None,
    collection_name: str = None,
    cml_token: str = None,
):
    """Parses local dbt schema + Excel definitions and indexes availability-enriched payloads into Qdrant."""
    yaml_path, excel_path = get_paths()
    
    if not yaml_path.exists():
        print(f"❌ Error: Schema YAML not found at {yaml_path}. Aborting ingestion.", flush=True)
        return

    # 1. Map Table Name -> Resolved Availability Date from Excel
    table_avail_map = {}
    if excel_path.exists():
        try:
            tables_df = pd.read_excel(excel_path, sheet_name="Tables")
            for _, r in tables_df.iterrows():
                t_name = str(r.get("Table Name", "")).strip().lower()
                a_date = r.get("Availability Date")
                if t_name and pd.notna(a_date) and str(a_date).strip().lower() != 'nan':
                    table_avail_map[t_name] = _resolve_relative_date(str(a_date).strip())
        except Exception as e:
            print(f"⚠️ Warning: Could not read Excel Availability Dates ({e})", flush=True)

    print(f"🌐 Loading local MetricFlow schema from: {yaml_path}...", flush=True)
    
    with open(yaml_path, "r") as f:
        schema = yaml.safe_load(f)

    metrics = schema.get("metrics", [])
    semantic_models = schema.get("semantic_models", [])

    catalog_texts = []
    metadatas = []

    # 2. Build lookup maps from Semantic Models
    sm_primary_entity = {}
    measure_to_time_dim = {}
    measure_to_sm_name = {}

    for sm in semantic_models:
        sm_name = sm.get("name")
        primary_entity = sm_name
        resolved_avail_date = table_avail_map.get(sm_name, "")
        
        for ent in sm.get("entities", []):
            if ent.get("type") == "primary":
                primary_entity = ent.get("name")
        sm_primary_entity[sm_name] = primary_entity

        for m in sm.get("measures", []):
            m_name = m.get("name")
            agg_time_col = m.get("agg_time_dimension")
            if m_name:
                measure_to_sm_name[m_name] = sm_name
                if agg_time_col:
                    measure_to_time_dim[m_name] = f"{primary_entity}__{agg_time_col}"

        # Process Dimensions
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

        # Process Entities
        for e in sm.get("entities", []):
            e_name = e.get("name")
            e_type = e.get("type", "unknown")
            e_expr = e.get("expr", e_name)
            e_desc = e.get("description", "No description provided.")

            searchable_text = (
                f"Entity Key: {e_name}\n"
                f"Key Type: {e_type}\n"
                f"Semantic Model / Table: {sm_name}\n"
                f"Expression: {e_expr}\n"
                f"Description: {e_desc}"
            )

            structured_payload = {
                "item_type": "entity",
                "name": e_name,
                "type": e_type,
                "semantic_model": sm_name,
                "expr": e_expr,
                "description": e_desc
            }

            catalog_texts.append(searchable_text)
            metadatas.append({
                "item_type": "entity",
                "name": e_name,
                "raw_json": json.dumps(structured_payload, indent=2),
            })

    # 3. Process Top-Level Metrics
    for m in metrics:
        m_name = m.get("name", "unknown")
        m_label = m.get("label", m_name)
        m_desc = m.get("description", "No description provided.")
        
        measure_ref = m.get("type_params", {}).get("measure")
        default_time_dim = measure_to_time_dim.get(measure_ref, "None")
        
        m_sm_name = measure_to_sm_name.get(measure_ref)
        m_avail_date = table_avail_map.get(m_sm_name, "")

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

    print(f"📊 Indexed {len(catalog_texts)} chunks into Qdrant with availability dates intact!", flush=True)

    reset_and_index(
        collection_name=collection_name,
        documents=catalog_texts,
        metadatas=metadatas,
        vectordb_server_url=vectordb_server_url,
        embed_rerank_url=embed_rerank_url,
        cml_token=cml_token,
        dataset_name="MetricFlow Catalog (YAML + Excel Ingestion)",
    )