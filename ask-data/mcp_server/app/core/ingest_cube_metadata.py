import os
import sys
import json
import yaml
from pathlib import Path
from typing import List, Dict, Any

# Bootstrap configuration
_ASK_DATA_ROOT = Path(__file__).resolve().parents[3] if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

import shared.config_loader as config_loader
config_loader.bootstrap(hint=_ASK_DATA_ROOT)

# Import the shared Qdrant client and remote embedding functions
from shared.qdrant_client import QdrantClient
from shared.embed_client import get_embeddings

# --- PATH CONFIGURATION ---
CUBE_YAML_PATH = os.path.join(_ASK_DATA_ROOT, "cube-service", "model", "cubes", "bni_schema_definitions.yaml")
CUBE_VALUE_MAPPINGS_JSON_PATH = os.path.join(_ASK_DATA_ROOT, "data", "value_mappings.json")


def ingest_documents(
    documents: List[str], 
    metadatas: List[Dict[str, Any]], 
    vectordb_server_url: str, 
    embed_rerank_url: str, 
    collection_name: str, 
    cml_token: str, 
    dataset_name: str = "Documents"
):
    """
    Generalized method to generate embeddings and store documents in Qdrant.
    """
    if not documents:
        print(f"⚠️ No documents provided for {dataset_name}.")
        return

    qdrant_client = QdrantClient(base_url=vectordb_server_url, token=cml_token)

    print(f"🧠 Generating embeddings for {len(documents)} {dataset_name} via {embed_rerank_url}...")
    embeddings, vector_dim = get_embeddings(documents, embed_rerank_url, cml_token, timeout=120.0)

    # Reset and recreate collection
    qdrant_client.delete_collection(name=collection_name)
    qdrant_client.create_collection(name=collection_name, vector_size=vector_dim)

    ids = list(range(1, len(documents) + 1))

    qdrant_client.add_documents(
        collection_name=collection_name,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
        ids=ids
    )
    print(f"✅ Successfully indexed {len(documents)} {dataset_name} into '{collection_name}'!")


def ingest_cube_catalog(yaml_path: str, vectordb_server_url: str, embed_rerank_url: str, collection_name: str, cml_token: str):
    """Parses Cube Data Model (YAML) and utilizes the generalized ingest method."""
    if not os.path.exists(yaml_path):
        print(f"⚠️ Cube Schema file not found at {yaml_path}")
        return

    print(f"📖 Reading Cube Schema from {yaml_path}...")
    with open(yaml_path, 'r', encoding="utf-8") as f:
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
                "embed_text": embed_text
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
                "embed_text": embed_text
            })

    ingest_documents(
        documents=documents,
        metadatas=metadatas,
        vectordb_server_url=vectordb_server_url,
        embed_rerank_url=embed_rerank_url,
        collection_name=collection_name,
        cml_token=cml_token,
        dataset_name="Cube Catalog Members"
    )


def ingest_value_mappings(json_path: str, vectordb_server_url: str, embed_rerank_url: str, collection_name: str, cml_token: str):
    """Parses Value Mappings (JSON) and utilizes the generalized ingest method."""
    if not os.path.exists(json_path):
        print(f"⚠️ Value Mappings file not found at {json_path}")
        return

    print(f"📖 Reading Value Mappings from {json_path}...")
    with open(json_path, 'r', encoding="utf-8") as f:
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
            "description": ctx
        })

    ingest_documents(
        documents=documents,
        metadatas=metadatas,
        vectordb_server_url=vectordb_server_url,
        embed_rerank_url=embed_rerank_url,
        collection_name=collection_name,
        cml_token=cml_token,
        dataset_name="Value Mappings"
    )