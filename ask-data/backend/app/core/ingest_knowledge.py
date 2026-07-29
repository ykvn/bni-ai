import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import chromadb
from chromadb.config import Settings  # 👈 Added Settings to configure SSL verification

try:
    import pysqlite3
    sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
except ImportError:
    pass

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

    chroma_server_url = env_map.get("CHROMA_SERVER_URL", "http://localhost:8000")
    collection_name = env_map.get("CHROMA_COLLECTION", "bank_abc_knowledge")

    # 🔑 Applied from frontend_entry pattern: Flexible CML token resolution
    cml_token = (
        env_map.get("CML_TOKEN") 
        or env_map.get("CDSW_API_KEY") 
        or env_map.get("CHROMA_SERVER_TOKEN") 
        or ""
    ).strip()

    docs_dir = os.path.abspath(os.path.join(backend_path, "..", "data", "documents"))
    if not os.path.exists(docs_dir):
        docs_dir = "/home/cdsw/ask-data/data/documents"

    parsed_url = urlparse(chroma_server_url)
    chroma_ssl = parsed_url.scheme == 'https'

    return {
        "docs_dir": docs_dir,
        "chroma_server_url": chroma_server_url,
        "chroma_ssl": chroma_ssl,
        "collection_name": collection_name,
        "cml_token": cml_token,
    }


def run_auto_ingest(
    docs_dir: str, 
    chroma_server_url: str, 
    chroma_ssl: bool, 
    collection_name: str,
    cml_token: str | None = None
):
    """Scans documents, flushes old context, and re-indexes into ChromaDB Endpoint."""
    parsed_url = urlparse(chroma_server_url)
    chroma_host = parsed_url.hostname
    chroma_port = parsed_url.port or (443 if chroma_ssl else 80)

    # 🔑 Applied from frontend_entry pattern: Prepare Bearer headers
    headers = {}
    if cml_token:
        headers["Authorization"] = f"Bearer {cml_token}"

    print(f"📡 Connecting to ChromaDB Endpoint at {chroma_host}:{chroma_port} (SSL: {chroma_ssl})...", flush=True)

    # 🔑 Applied from frontend_entry pattern: Pass headers AND disable SSL verification 
    # to stop httpx from stripping headers during CML Auth redirects.
    chroma_client = chromadb.HttpClient(
        host=chroma_host, 
        port=chroma_port, 
        ssl=chroma_ssl,
        headers=headers if headers else None,
        settings=Settings(chroma_server_ssl_verify=False)  # 👈 Prevents SSL verification drops
    )

    try:
        chroma_client.delete_collection(name=collection_name)
        print(f"🧹 [RAG ENGINE] Flushed old vector collection cache: '{collection_name}'", flush=True)
    except Exception as e:
        print(f"ℹ️ [RAG ENGINE] Notice during collection reset: {str(e)}", flush=True)

    collection = chroma_client.get_or_create_collection(name=collection_name)
    print(f"✅ Successfully connected to collection: '{collection_name}'", flush=True)

    if not os.path.exists(docs_dir):
        print(f"⚠️ [RAG ENGINE] Targeted directory path does not exist: '{docs_dir}'. Sync suspended.", flush=True)
        return

    pdf_files = [f for f in os.listdir(docs_dir) if f.lower().endswith('.pdf')]
    if not pdf_files:
        print(f"⚠️ [RAG ENGINE] No PDF files found in '{docs_dir}'. Knowledge base empty.", flush=True)
        return

    print(f"📄 Found {len(pdf_files)} PDF file(s) in {docs_dir}: {pdf_files}", flush=True)
    print("🧠 Loading all-MiniLM-L6-v2 embedding weights...", flush=True)
    
    embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
    print("✅ Embedding model loaded into memory!", flush=True)

    global_chunk_counter = 0

    for pdf_file in pdf_files:
        file_path = os.path.join(docs_dir, pdf_file)
        print(f"📄 Processing document: {pdf_file}...", flush=True)

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
                print(f"⚠️ No text extracted from {pdf_file}", flush=True)
                continue

            print(f"✂️ Fragmented into {len(text_fragments)} chunks. Generating embeddings...", flush=True)
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
            print(f"💾 Committed {len(text_fragments)} vectors for {pdf_file} to ChromaDB.", flush=True)

        except Exception as file_error:
            print(f"❌ Error parsing file {pdf_file}: {str(file_error)}", flush=True)
            continue

    print(f"🎉 Build pipeline complete! Total active vectors in cluster: {collection.count()}", flush=True)