import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
import urllib3
import requests

# Suppress SSL warnings for internal CML certificates[cite: 13]
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from pypdf import PdfReader


class CMLQdrantClient:
    """
    A lightweight Qdrant REST Client built on Python 'requests'.
    Uses CML Bearer authentication, SSL bypass, and extended gateway timeouts[cite: 13].
    """
    def __init__(self, base_url: str, token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.verify = False  # Bypasses internal CML SSL certificate issues[cite: 13]
        
        if token:
            # Send BOTH Bearer token for CML and api-key for Qdrant authentication[cite: 13]
            self.session.headers.update({
                "Authorization": f"Bearer {token}",
                "api-key": token
            })
        else:
            print("⚠️ Notice: No CML token loaded. Request may fail if CML Application authentication is enabled.", flush=True)

        self._warmup_gateway()

    def _warmup_gateway(self) -> None:
        """Pings Qdrant health endpoint to warm up CML OAuth Proxy session[cite: 13]."""
        url = f"{self.base_url}/collections"
        for attempt in range(1, 4):
            try:
                res = self.session.get(url, timeout=120)
                if res.status_code == 200:
                    print("⚡ CML Gateway proxy connection established successfully.", flush=True)
                    return
            except Exception:
                time.sleep(2)

    def delete_collection(self, name: str) -> None:
        """Deletes an existing collection if present[cite: 13]."""
        url = f"{self.base_url}/collections/{name}"
        try:
            res = self.session.delete(url, timeout=120)
            if res.status_code == 200:
                print(f"🧹 [RAG ENGINE] Flushed old vector collection cache: '{name}'", flush=True)
            else:
                print(f"ℹ️ [RAG ENGINE] Collection reset notice (Status {res.status_code})", flush=True)
        except Exception as e:
            print(f"ℹ️ [RAG ENGINE] Notice during collection reset: {e}", flush=True)

    def create_collection(self, name: str, vector_size: int) -> None:
        """Creates a new collection in Qdrant configured for vector embeddings[cite: 13]."""
        url = f"{self.base_url}/collections/{name}"
        payload = {
            "vectors": {
                "size": vector_size,
                "distance": "Cosine"
            }
        }
        res = self.session.put(url, json=payload, timeout=120)
        res.raise_for_status()

    def add_documents(
        self, 
        collection_name: str, 
        documents: list[str], 
        embeddings: list[list[float]], 
        metadatas: list[dict], 
        ids: list[int],
        batch_size: int = 100
    ) -> None:
        """Pushes text fragments and vector embeddings to Qdrant in safe batches[cite: 13]."""
        url = f"{self.base_url}/collections/{collection_name}/points?wait=true"
        
        all_points = []
        for point_id, doc, emb, meta in zip(ids, documents, embeddings, metadatas):
            payload = {**meta, "page_content": doc}
            all_points.append({
                "id": point_id,
                "vector": emb,
                "payload": payload
            })

        # Batch upload points to prevent HTTP 413 / Gateway Timeout errors[cite: 13]
        for i in range(0, len(all_points), batch_size):
            batch = all_points[i:i + batch_size]
            request_body = {"points": batch}
            res = self.session.put(url, json=request_body, timeout=120)
            res.raise_for_status()

    def get_count(self, collection_name: str) -> int:
        """Returns active vector count in collection[cite: 13]."""
        url = f"{self.base_url}/collections/{collection_name}/points/count"
        try:
            res = self.session.post(url, json={"exact": True}, timeout=120)
            if res.status_code == 200:
                return res.json().get("result", {}).get("count", 0)
        except Exception:
            pass
        return 0


def _load_env_file(backend_dir) -> dict[str, str]:
    """Ensure global environment variables are loaded[cite: 13]."""
    try:
        from shared.config_loader import load_project_env
        load_project_env()
    except ImportError:
        pass
    return {}


def build_ingest_config(backend_dir, env=None):
    """Resolve document, Qdrant, and embed-rerank settings explicitly from environment[cite: 13]."""
    backend_path = os.path.abspath(str(backend_dir))
    env_map = dict(env or os.environ)
    env_map.update(_load_env_file(backend_path))

    docs_dir = env_map.get("DOCS_DIR")
    if not docs_dir:
        docs_dir = os.path.abspath(os.path.join(backend_path, "..", "data", "documents"))

    # Safely handle missing env variables without crashing on .strip()[cite: 13]
    qdrant_server_url = (env_map.get("QDRANT_SERVER_URL") or "").strip()
    embed_rerank_url = (
        env_map.get("EMBED_RERANK_URL") 
        or env_map.get("SEMANTIC_ENGINE_URL") 
        or "http://127.0.0.1:8090"
    ).strip().rstrip("/")
    
    collection_name = (env_map.get("QDRANT_COLLECTION") or "").strip()
    cml_token = (env_map.get("CML_TOKEN") or "").strip()

    parsed_url = urlparse(qdrant_server_url)
    qdrant_ssl = parsed_url.scheme == 'https'

    return {
        "docs_dir": docs_dir,
        "qdrant_server_url": qdrant_server_url,
        "embed_rerank_url": embed_rerank_url,
        "qdrant_ssl": qdrant_ssl,
        "collection_name": collection_name,
        "cml_token": cml_token,
    }


def _get_remote_embeddings(texts: list[str], engine_url: str, cml_token: str) -> tuple[list[list[float]], int]:
    """Calls embed-rerank microservice to generate batch embeddings."""
    headers = {}
    if cml_token:
        headers["Authorization"] = f"Bearer {cml_token}"
        headers["X-CDSW-API-Key"] = cml_token

    res = requests.post(
        f"{engine_url}/v1/embeddings",
        json={"input": texts},
        headers=headers,
        verify=False,
        timeout=120.0
    )
    res.raise_for_status()
    payload = res.json()
    return payload["embeddings"], payload["dimension"]


def run_auto_ingest(
    docs_dir: str, 
    qdrant_server_url: str, 
    embed_rerank_url: str,
    qdrant_ssl: bool, 
    collection_name: str,
    cml_token: str | None = None
):
    """Scans documents, flushes old context, and re-indexes into Qdrant via remote embed-rerank REST calls."""
    if not qdrant_server_url or not collection_name:
        print("❌ [RAG ENGINE] Error: QDRANT_SERVER_URL or QDRANT_COLLECTION is not configured.", flush=True)
        return

    print(f"📡 Connecting to Qdrant Endpoint at {qdrant_server_url}...", flush=True)
    qdrant_client = CMLQdrantClient(base_url=qdrant_server_url, token=cml_token or "")

    # Test connection and fetch dimension from remote embed-rerank microservice
    print(f"🧠 Querying vector dimension from embed-rerank at {embed_rerank_url}...", flush=True)
    _, vector_dim = _get_remote_embeddings(["ping"], embed_rerank_url, cml_token or "")
    print(f"✅ embed-rerank connection established! (Vector Dimension: {vector_dim})", flush=True)

    # Reset and recreate collection in Qdrant using the remote vector dimension
    qdrant_client.delete_collection(name=collection_name)
    qdrant_client.create_collection(name=collection_name, vector_size=vector_dim)
    print(f"✅ Successfully created/reset collection: '{collection_name}'", flush=True)

    if not os.path.exists(docs_dir):
        print(f"⚠️ [RAG ENGINE] Targeted directory path does not exist: '{docs_dir}'. Sync suspended.", flush=True)
        return

    pdf_files = [f for f in os.listdir(docs_dir) if f.lower().endswith('.pdf')]
    if not pdf_files:
        print(f"⚠️ [RAG ENGINE] No PDF files found in '{docs_dir}'. Knowledge base empty.", flush=True)
        return

    print(f"📄 Found {len(pdf_files)} PDF file(s) in {docs_dir}: {pdf_files}", flush=True)
    global_chunk_counter = 1

    for pdf_file in pdf_files:
        file_path = os.path.join(docs_dir, pdf_file)
        print(f"📄 Processing document: {pdf_file}...", flush=True)

        try:
            reader = PdfReader(file_path)
            text_fragments = []
            metadata_payloads = []

            chunk_size = 1500
            overlap = 300

            # Page-aware extraction to preserve page metadata[cite: 13]
            for page_idx, page in enumerate(reader.pages, start=1):
                extracted_text = page.extract_text()
                if not extracted_text:
                    continue

                for i in range(0, len(extracted_text), chunk_size - overlap):
                    fragment = extracted_text[i:i + chunk_size].strip()
                    if len(fragment) > 50:
                        text_fragments.append(fragment)
                        metadata_payloads.append({
                            "source_file": pdf_file,
                            "page_number": page_idx
                        })

            if not text_fragments:
                print(f"⚠️ No usable text extracted from {pdf_file}", flush=True)
                continue

            print(f"✂️ Fragmented into {len(text_fragments)} chunks. Requesting remote embeddings...", flush=True)
            vector_embeddings, _ = _get_remote_embeddings(text_fragments, embed_rerank_url, cml_token or "")

            document_ids = [global_chunk_counter + idx for idx in range(len(text_fragments))]

            qdrant_client.add_documents(
                collection_name=collection_name,
                documents=text_fragments,
                embeddings=vector_embeddings,
                metadatas=metadata_payloads,
                ids=document_ids,
            )

            global_chunk_counter += len(text_fragments)
            print(f"💾 Committed {len(text_fragments)} vectors for {pdf_file} to Qdrant.", flush=True)

        except Exception as file_error:
            print(f"❌ Error parsing file {pdf_file}: {str(file_error)}", flush=True)
            continue

    total_count = qdrant_client.get_count(collection_name=collection_name)
    print(f"🎉 Build pipeline complete! Total active vectors in cluster: {total_count}", flush=True)