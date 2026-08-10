"""
Knowledge base ingestion: PDF documents chunked page-aware into Qdrant.

Uses the shared ``ingest_common`` bootstrap so environment resolution and
Qdrant/embed client construction behave identically to the SQL and Cube
pipelines. Unlike those metadata pipelines, documents are processed and
uploaded per-file with page-aware chunking, so the collection flush happens
up front and vectors are appended file-by-file.
"""
import os

from pypdf import PdfReader

from shared.embed_client import get_embeddings
from shared.qdrant_client import QdrantClient

from app.core.ingest_common import bootstrap_env

# Standardized project-root bootstrap (idempotent, shared across all pipelines)
bootstrap_env()


def build_ingest_config(backend_dir, env=None):
    """
    Resolve document, Qdrant, and embed-rerank settings explicitly from
    environment, mirroring the same env vars used by the SQL/Cube pipelines.
    """
    backend_path = os.path.abspath(str(backend_dir))
    env_map = dict(env or os.environ)

    docs_dir = env_map.get("DOCS_DIR")
    if not docs_dir:
        docs_dir = os.path.abspath(os.path.join(backend_path, "..", "data", "documents"))

    # Safely handle missing env variables without crashing on .strip()
    qdrant_server_url = (env_map.get("VECTORDB_SERVER_URL") or "").strip()
    embed_rerank_url = (env_map.get("EMBED_RERANK_URL") or "").strip().rstrip("/")
    collection_name = (env_map.get("DOCUMENT_COLLECTION") or "").strip()
    cml_token = (env_map.get("CML_TOKEN") or "").strip()

    return {
        "docs_dir": docs_dir,
        "qdrant_server_url": qdrant_server_url,
        "embed_rerank_url": embed_rerank_url,
        "collection_name": collection_name,
        "cml_token": cml_token,
    }


def run_auto_ingest(
    docs_dir: str,
    qdrant_server_url: str,
    embed_rerank_url: str,
    collection_name: str,
    cml_token: str | None = None,
):
    """
    Scans documents, flushes old collection, and re-indexes into Qdrant via
    remote embed-rerank REST calls.
    """
    if not qdrant_server_url or not collection_name:
        print(
            "❌ [RAG ENGINE] Error: VECTORDB_SERVER_URL or DOCUMENT_COLLECTION "
            "is not configured.",
            flush=True,
        )
        return

    print(f"📡 Connecting to Qdrant Endpoint at {qdrant_server_url}...", flush=True)
    qdrant_client = QdrantClient(base_url=qdrant_server_url, token=cml_token or "")

    # Test connection and fetch dimension from remote embed-rerank microservice
    print(
        f"🧠 Querying vector dimension from embed-rerank at {embed_rerank_url}...",
        flush=True,
    )
    _, vector_dim = get_embeddings(["ping"], embed_rerank_url, cml_token or "", timeout=120.0)
    print(
        f"✅ embed-rerank connection established! (Vector Dimension: {vector_dim})",
        flush=True,
    )

    # Reset and recreate collection in Qdrant using the remote vector dimension
    qdrant_client.delete_collection(name=collection_name)
    qdrant_client.create_collection(name=collection_name, vector_size=vector_dim)
    print(f"✅ Successfully created/reset collection: '{collection_name}'", flush=True)

    if not os.path.exists(docs_dir):
        print(
            f"⚠️ [RAG ENGINE] Targeted directory path does not exist: '{docs_dir}'. "
            "Sync suspended.",
            flush=True,
        )
        return

    pdf_files = [f for f in os.listdir(docs_dir) if f.lower().endswith(".pdf")]
    if not pdf_files:
        print(
            f"⚠️ [RAG ENGINE] No PDF files found in '{docs_dir}'. Knowledge base empty.",
            flush=True,
        )
        return

    print(
        f"📄 Found {len(pdf_files)} PDF file(s) in {docs_dir}: {pdf_files}",
        flush=True,
    )
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

            # Page-aware extraction to preserve page metadata
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
                            "page_number": page_idx,
                        })

            if not text_fragments:
                print(f"⚠️ No usable text extracted from {pdf_file}", flush=True)
                continue

            print(
                f"✂️ Fragmented into {len(text_fragments)} chunks. "
                "Requesting remote embeddings...",
                flush=True,
            )
            vector_embeddings, _ = get_embeddings(
                text_fragments, embed_rerank_url, cml_token or "", timeout=120.0
            )

            document_ids = [global_chunk_counter + idx for idx in range(len(text_fragments))]

            qdrant_client.add_documents(
                collection_name=collection_name,
                documents=text_fragments,
                embeddings=vector_embeddings,
                metadatas=metadata_payloads,
                ids=document_ids,
            )

            global_chunk_counter += len(text_fragments)
            print(
                f"💾 Committed {len(text_fragments)} vectors for {pdf_file} to Qdrant.",
                flush=True,
            )

        except Exception as file_error:
            print(f"❌ Error parsing file {pdf_file}: {str(file_error)}", flush=True)
            continue

    total_count = qdrant_client.get_count(collection_name=collection_name)
    print(
        f"🎉 Build pipeline complete! Total active vectors in cluster: {total_count}",
        flush=True,
    )