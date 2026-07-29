import os
from pathlib import Path

import chromadb
try:
    __import__('pysqlite3')
    import sys
    sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
except ImportError:
    pass

from urllib.parse import urlparse
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer


def _load_env_file(backend_dir) -> dict[str, str]:
    """Load simple KEY=VALUE entries from the nearest .env files."""
    backend_path = Path(backend_dir).resolve()
    candidates = [
        backend_path / ".env",
        backend_path.parent / ".env",
        backend_path.parent / "mcp_server" / ".env",
        backend_path.parent.parent / "mcp_server" / ".env",
    ]

    values: dict[str, str] = {}
    for candidate in candidates:
        if not candidate.exists():
            continue
        for raw_line in candidate.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
        break
    return values


def build_ingest_config(backend_dir, env=None):
    """Resolve the document and Chroma settings used for ingestion."""
    backend_path = os.path.abspath(str(backend_dir))
    env_map = dict(env or os.environ)
    env_map.update(_load_env_file(backend_path))

    # Now we need the ChromaDB server URL, not the local persist_dir
    chroma_server_url = env_map.get("CHROMA_SERVER_URL", "http://localhost:8000")
    collection_name = env_map.get("CHROMA_COLLECTION", "bank_abc_knowledge")

    docs_dir = os.path.abspath(os.path.join(backend_path, "..", "data", "documents"))
    if not os.path.exists(docs_dir):
        docs_dir = "/home/cdsw/ask-data/data/documents"

    # Parse host and port from the URL
    parsed_url = urlparse(chroma_server_url)

    return {
        "docs_dir": docs_dir,
        "chroma_host": parsed_url.hostname,
        "chroma_port": parsed_url.port,
        "collection_name": collection_name,
    }


def run_auto_ingest(docs_dir: str, chroma_host: str, chroma_port: int, collection_name: str):
    """
    Scans the documents directory, flushes old context nodes, and performs
    a clean re-index of all policy manuals directly into ChromaDB.
    """
    print(f"Connecting to ChromaDB server at {chroma_host}:{chroma_port}")
    chroma_client = chromadb.HttpClient(host=chroma_host, port=chroma_port)

    try:
        chroma_client.delete_collection(name=collection_name)
        print(f"🧹 [RAG ENGINE] Flushed old vector collection cache: '{collection_name}'")
    except Exception:
        pass

    collection = chroma_client.get_or_create_collection(name=collection_name)

    if not os.path.exists(docs_dir):
        print(f"⚠️ [RAG ENGINE] Targeted directory path does not exist: '{docs_dir}'. Sync cycle suspended.")
        return

    pdf_files = [f for f in os.listdir(docs_dir) if f.lower().endswith('.pdf')]
    if not pdf_files:
        print(f"⚠️ [RAG ENGINE] No source policy manuals detected inside '{docs_dir}'. Knowledge base remains empty.")
        return

    print("🧠 [RAG ENGINE] Loading local all-MiniLM-L6-v2 vectorization engine weights...")
    embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

    global_chunk_counter = 0

    for pdf_file in pdf_files:
        file_path = os.path.join(docs_dir, pdf_file)
        print(f"📄 [RAG ENGINE] Re-indexing asset parameters from: {pdf_file}")

        try:
            reader = PdfReader(file_path)
            raw_document_text = ""

            for page in reader.pages:
                extracted_text = page.extract_text()
                if extracted_text:
                    raw_document_text += extracted_text + "\n"

            chunk_size = 1500
            overlap = 300
            text_fragments = []

            for i in range(0, len(raw_document_text), chunk_size - overlap):
                fragment = raw_document_text[i:i + chunk_size].strip()
                if len(fragment) > 50:
                    text_fragments.append(fragment)

            if not text_fragments:
                continue

            print(f"✂️ [RAG ENGINE] Fragmented {pdf_file} into {len(text_fragments)} segments. Generating embeddings...")
            vector_embeddings = embedding_model.encode(text_fragments).tolist()

            document_ids = [f"chunk_{global_chunk_counter + idx}" for idx in range(len(text_fragments))]
            metadata_payloads = [{"source_file": pdf_file} for _ in text_fragments]

            collection.add(
                documents=text_fragments,
                embeddings=vector_embeddings,
                metadatas=metadata_payloads,
                ids=document_ids,
            )

            global_chunk_counter += len(text_fragments)
            print(f"💾 [RAG ENGINE] Successfully committed {len(text_fragments)} vector items for {pdf_file} to disk storage.")

        except Exception as file_error:
            print(f"❌ [RAG ENGINE] Error parsing file {pdf_file}: {str(file_error)}")
            continue

    print(f"🎉 [RAG ENGINE] Database build pipeline resolved! {collection.count()} total vectors are active in the cluster.")
