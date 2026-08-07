import os
import sys
import json
import yaml
from pathlib import Path

# Bootstrap configuration
_ASK_DATA_ROOT = Path(__file__).resolve().parents[3] if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

import shared.config_loader as config_loader
config_loader.bootstrap(hint=_ASK_DATA_ROOT)

# Import the existing standardized Qdrant client and remote embedding functions
from app.core.ingest_knowledge import CMLQdrantClient, _get_remote_embeddings

def ingest_golden_queries(json_path: str, qdrant_url: str, embed_url: str, collection_name: str, cml_token: str):
    """Embeds user intents and stores the verified SQL templates in Qdrant."""
    if not os.path.exists(json_path):
        print(f"⚠️ Golden queries file not found at {json_path}")
        return

    print(f"📖 Reading Golden Queries from {json_path}...")
    with open(json_path, 'r', encoding="utf-8") as f:
        queries = json.load(f)

    if not queries:
        return

    qdrant_client = CMLQdrantClient(base_url=qdrant_url, token=cml_token)
    
    # We embed the natural language intent so it matches the user's question semantically
    intents = [q.get("user_intent", "") for q in queries]
    print(f"🧠 Generating embeddings for {len(intents)} golden queries via {embed_url}...")
    
    embeddings, vector_dim = _get_remote_embeddings(intents, embed_url, cml_token)

    # Reset and recreate collection
    qdrant_client.delete_collection(name=collection_name)
    qdrant_client.create_collection(name=collection_name, vector_size=vector_dim)

    # Prepare payloads
    metadatas = [
        {
            "user_intent": q.get("user_intent", ""),
            "sql_template": q.get("sql_template", ""),
            "complexity": q.get("complexity", "unknown"),
            "data_type": "golden_query"
        }
        for q in queries
    ]
    ids = list(range(1, len(queries) + 1))

    qdrant_client.add_documents(
        collection_name=collection_name,
        documents=intents,
        embeddings=embeddings,
        metadatas=metadatas,
        ids=ids
    )
    print(f"✅ Successfully indexed {len(queries)} Golden Queries into '{collection_name}'!")


def ingest_schema(yaml_path: str, qdrant_url: str, embed_url: str, collection_name: str, cml_token: str):
    """Parses database schema YAML and chunks it by table for vector search."""
    if not os.path.exists(yaml_path):
        print(f"⚠️ Schema file not found at {yaml_path}")
        return

    print(f"📖 Reading Schema from {yaml_path}...")
    with open(yaml_path, 'r', encoding="utf-8") as f:
        schema = yaml.safe_load(f)

    tables = schema.get("tables", [])
    if not tables:
        return

    qdrant_client = CMLQdrantClient(base_url=qdrant_url, token=cml_token)
    
    table_texts = []
    metadatas = []
    
    # Chunk by table to keep context windows small and precise
    for table in tables: #[cite: 15]
        table_name = table.get("name", "unknown") #[cite: 15]
        desc = table.get("description", "") #[cite: 15]
        
        # Include column names AND descriptions for richer semantic matching
        col_details = []
        for c in table.get("columns", []): #[cite: 15]
            c_name = c.get("name", "")
            c_desc = c.get("description", "")
            col_details.append(f"{c_name} ({c_desc})" if c_desc else c_name)
            
        cols_formatted = ", ".join(col_details)
        
        searchable_text = f"Table: {table_name}\nDescription: {desc}\nColumns: {cols_formatted}"
        table_texts.append(searchable_text) #[cite: 15]
        
        metadatas.append({
            "table_name": table_name,
            "raw_yaml": yaml.dump(table), # Store the raw YAML structure to feed to the LLM
            "data_type": "schema_table"
        })

    print(f"🧠 Generating embeddings for {len(table_texts)} tables via {embed_url}...")
    embeddings, vector_dim = _get_remote_embeddings(table_texts, embed_url, cml_token)

    # Reset and recreate collection
    qdrant_client.delete_collection(name=collection_name)
    qdrant_client.create_collection(name=collection_name, vector_size=vector_dim)

    ids = list(range(1, len(table_texts) + 1))
    qdrant_client.add_documents(
        collection_name=collection_name,
        documents=table_texts,
        embeddings=embeddings,
        metadatas=metadatas,
        ids=ids
    )
    print(f"✅ Successfully indexed {len(table_texts)} Schema Tables into '{collection_name}'!")