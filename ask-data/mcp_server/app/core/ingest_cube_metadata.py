"""
Cube metadata ingestion: Cube semantic model (YAML) + value mappings (JSON).

Uses the shared ``ingest_common`` bootstrap and ``reset_and_index`` routine
so this pipeline behaves identically to the SQL and knowledge pipelines.
"""
import json
import os
import yaml
from typing import List, Dict, Any

from app.core.ingest_common import bootstrap_env, reset_and_index, resolve_data_path

# Standardized project-root bootstrap (idempotent, shared across all pipelines)
bootstrap_env()

# --- PATH CONFIGURATION ---
CUBE_YAML_PATH = resolve_data_path("cube_service/model/cubes/bni_cube_definitions.yaml")
CUBE_VALUE_MAPPINGS_JSON_PATH = resolve_data_path("data/bni_cube_value_mappings.json")


def ingest_cube_catalog(
    yaml_path: str,
    vectordb_server_url: str,
    embed_rerank_url: str,
    collection_name: str,
    cml_token: str,
):
    """Parses Cube Data Model (YAML) and indexes catalog members."""
    if not os.path.exists(yaml_path):
        print(f"⚠️ Cube Schema file not found at {yaml_path}")
        return

    print(f"📖 Reading Cube Schema from {yaml_path}...")
    with open(yaml_path, "r", encoding="utf-8") as f:
        cube_data = yaml.safe_load(f)

    documents = []
    metadatas = []

    for cube in cube_data.get("cubes", []):
        cube_name = cube["name"]

        # Index Measures
        for m in cube.get("measures", []):
            full_member_name = f"{cube_name}.{m['name']}"
            embed_text = f"Cube: {cube_name} | Type: Measure | Member: {full_member_name} | Description: {m['description']}"

            documents.append(embed_text)
            metadatas.append({
                "cube": cube_name,
                "member_type": "measure",
                "member_name": full_member_name,
                "description": m["description"],
                "embed_text": embed_text,
            })

        # Index Dimensions
        for d in cube.get("dimensions", []):
            full_member_name = f"{cube_name}.{d['name']}"
            embed_text = f"Cube: {cube_name} | Type: Dimension | Member: {full_member_name} | Description: {d['description']}"

            documents.append(embed_text)
            metadatas.append({
                "cube": cube_name,
                "member_type": "dimension",
                "member_name": full_member_name,
                "description": d["description"],
                "embed_text": embed_text,
            })

    reset_and_index(
        collection_name=collection_name,
        documents=documents,
        metadatas=metadatas,
        vectordb_server_url=vectordb_server_url,
        embed_rerank_url=embed_rerank_url,
        cml_token=cml_token,
        dataset_name="Cube Catalog Members",
    )


def ingest_value_mappings(
    json_path: str,
    vectordb_server_url: str,
    embed_rerank_url: str,
    collection_name: str,
    cml_token: str,
):
    """Parses Value Mappings (JSON) and indexes them."""
    if not os.path.exists(json_path):
        print(f"⚠️ Value Mappings file not found at {json_path}")
        return

    print(f"📖 Reading Value Mappings from {json_path}...")
    with open(json_path, "r", encoding="utf-8") as f:
        value_mappings = json.load(f)

    documents = []
    metadatas = []

    for item in value_mappings:
        member_name = f"{item['Table Name']}.{item['Column Name']}"
        db_val = item["Database Value"]
        synonyms = item["Synonyms / User Phrasing"]
        ctx = item.get("Description / Context", "")

        embed_text = f"Member: {member_name} | Value: {db_val} | Synonyms: {synonyms} | Context: {ctx}"

        documents.append(embed_text)
        metadatas.append({
            "table_name": item["Table Name"],
            "column_name": item["Column Name"],
            "member_name": member_name,
            "db_value": db_val,
            "synonyms": synonyms,
            "description": ctx,
        })

    reset_and_index(
        collection_name=collection_name,
        documents=documents,
        metadatas=metadatas,
        vectordb_server_url=vectordb_server_url,
        embed_rerank_url=embed_rerank_url,
        cml_token=cml_token,
        dataset_name="Value Mappings",
    )