import os
import sys
from pathlib import Path
from urllib.parse import urlparse
import urllib3
import requests

# Suppress SSL warnings (matches frontend_entry.py behavior)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    import pysqlite3
    sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
except ImportError:
    pass

from pypdf import PdfReader
from sentence_transformers import SentenceTransformer


class CMLChromaClient:
    """
    A lightweight ChromaDB HTTP Client built on Python 'requests'.
    Uses the exact authentication & SSL pattern as frontend_entry.py.
    """
    def __init__(self, base_url: str, token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.verify = False  # Bypasses CML internal SSL handshake issues
        if token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})

    def delete_collection(self, name: str) -> None:
        """Deletes an existing collection if present."""
        url = f"{self.base_url}/api/v1/collections/{name}"
        try:
            self.session.delete(url, timeout=30)
        except Exception:
            pass

    def get_or_create_collection_id(self, name: str) -> str:
        """Gets an existing collection ID or creates a new one."""
        # 1. Try fetching existing collection
        get_url = f"{self.base_url}/api/v1/collections/{name}"
        res = self.session.get(get_url, timeout=30)
        if res.status_code == 200:
            return res.json()["id"]

        # 2. Create if not found
        create_url = f"{self.base_url}/api/v1/collections"
        payload = {"name": name, "get_or_create": True}
        res = self.session.post(create_url, json=payload, timeout=30)
        res.raise_for_status()
        return res.json()["id"]

    def add_documents(
        self, 
        collection_id: str, 
        documents: list[str], 
        embeddings: list[list[float]], 
        metadatas: list[dict], 
        ids: list[str]
    ) -> None:
        """Pushes text fragments and vector embeddings to ChromaDB."""
        url = f"{self.base_url}/api/v1/collections/{collection_id}/add"
        payload = {
            "documents": documents,
            "embeddings": embeddings,
            "metadatas": metadatas,
            "ids": ids
        }
        res = self.session.post(url, json=payload, timeout=120)
        res.raise_for_status()

    def get_count(self, collection_id: str) -> int:
        """Returns active vector count in collection."""
        url = f"{self.base_url}/api/v1/collections/{collection_id}/count"
        res = self.session.get(url, timeout=30)
        if res.status_code == 200:
            return res.json()
        return 0


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
    """Resolve document and Chroma settings used for ingestion."""
    backend_path = os.path.abspath(str(backend_dir))
    env_map = dict(env or os.environ)
    env_map.update(_load_env_file(backend_path))

    chroma_server_url = env_map.get("CHROMA_SERVER_URL", "http://localhost:8000")
    collection_name = env_map.get("CHROMA_COLLECTION", "bank_abc_knowledge")

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
    """Scans documents, flushes old context, and re-indexes into ChromaDB via requests."""
    print(f"📡 Connecting to ChromaDB Endpoint at {chroma_server_url}...", flush=True)

    # Instantiate custom requests-backed client
    chroma_client = CMLChromaClient(base_url=chroma_server_url, token=cml_token or "")

    # Reset collection
    chroma_client.delete_collection(name=collection_name)
    print(f"🧹 [RAG ENGINE] Flushed old vector collection cache: '{collection_name}'", flush=True)

    collection_id = chroma_client.get_or_create_collection_id(name=collection_name)
    print(f"✅ Successfully connected to collection ID: '{collection_id}'", flush=True)

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

            chroma_client.add_documents(
                collection_id=collection_id,
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

    total_count = chroma_client.get_count(collection_id=collection_id)
    print(f"🎉 Build pipeline complete! Total active vectors in cluster: {total_count}", flush=True)