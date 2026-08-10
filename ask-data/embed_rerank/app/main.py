import os
import sys
from contextlib import asynccontextmanager
from typing import List, Optional, Union

from fastapi import FastAPI, Header, HTTPException, Depends, status
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer, CrossEncoder

from shared.model_resolver import resolve_model_path
from shared.cml_auth import get_cml_token

# ---------------------------------------------------------------------
# Global Model State
# ---------------------------------------------------------------------
embedder = None
reranker = None
VECTOR_DIMENSION = 0

model_metadata = {
    "embed_model": {
        "name": os.getenv("EMBED_MODEL_NAME", ""),
        "source": "UNINITIALIZED",
        "path": "N/A"
    },
    "rerank_model": {
        "name": os.getenv("RERANK_MODEL_NAME", ""),
        "source": "UNINITIALIZED",
        "path": "N/A"
    }
}

# ---------------------------------------------------------------------
# Model resolution uses shared.model_resolver.resolve_model_path
# ---------------------------------------------------------------------

# ---------------------------------------------------------------------
# Lifespan Context Manager (Startup / Shutdown)
# ---------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global embedder, reranker, VECTOR_DIMENSION, model_metadata
    
    print("\n" + "="*75)
    print("🚀 INITIALIZING EMBED-RERANK SEMANTIC ENGINE")
    print("="*75 + "\n")

    # 1. Resolve and Load Embedding Model
    emb_name = model_metadata["embed_model"]["name"]
    emb_path, emb_source = resolve_model_path(emb_name)
    model_metadata["embed_model"]["source"] = emb_source
    model_metadata["embed_model"]["path"] = emb_path

    print(f"⏳ Loading Embedding Model '{emb_name}' into CPU RAM...")
    embedder = SentenceTransformer(emb_path)
    VECTOR_DIMENSION = embedder.get_embedding_dimension()
    
    # 2. Resolve and Load Reranker Model
    rerank_name = model_metadata["rerank_model"]["name"]
    rerank_path, rerank_source = resolve_model_path(rerank_name)
    model_metadata["rerank_model"]["source"] = rerank_source
    model_metadata["rerank_model"]["path"] = rerank_path

    print(f"⏳ Loading Cross-Encoder Reranker '{rerank_name}' into CPU RAM...")
    reranker = CrossEncoder(rerank_path)

    print(f"✅ Both models successfully loaded! Vector Dimension: {VECTOR_DIMENSION}\n")
    
    yield  
    
    print("🧹 Shutting down semantic engine and releasing RAM...[cite: 11]")
    embedder = None
    reranker = None


app = FastAPI(
    title="Embed & Rerank Microservice",
    description="Dedicated CML microservice for BGE-M3 Embeddings and Cross-Encoder Reranking",
    lifespan=lifespan
)


# ---------------------------------------------------------------------
# CML Token Authentication Dependency
# ---------------------------------------------------------------------
def verify_cml_token(
    authorization: Optional[str] = Header(None),
    x_cdsw_api_key: Optional[str] = Header(None)
):
    """
    Validates CML_TOKEN passed via Authorization Bearer or X-CDSW-API-Key header.
    If ENFORCE_CML_AUTH is 'true', rejects unauthorized requests.
    """
    expected_token = get_cml_token()
    enforce_auth = os.getenv("ENFORCE_CML_AUTH", "false").lower() == "true"

    if not enforce_auth or not expected_token:
        return True

    incoming_token = None
    if authorization and authorization.startswith("Bearer "):
        incoming_token = authorization.split("Bearer ")[1].strip()
    elif x_cdsw_api_key:
        incoming_token = x_cdsw_api_key.strip()

    if incoming_token != expected_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing CML Authentication Token."
        )
    return True


# ---------------------------------------------------------------------
# Request & Response Schemas
# ---------------------------------------------------------------------
class EmbedRequest(BaseModel):
    input: Union[str, List[str]]


class RerankRequest(BaseModel):
    query: str
    documents: List[str]
    top_n: Optional[int] = 5


# ---------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------
@app.get("/")
def root_health_check():
    """Satisfies CML Application health checks on GET /"""
    return {
        "status": "healthy",
        "service": "embed-rerank",
        "embedding_model": model_metadata["embed_model"]["name"],
        "reranker_model": model_metadata["rerank_model"]["name"],
        "vector_dimension": VECTOR_DIMENSION
    }


@app.get("/health")
def health_check():
    return root_health_check()


@app.get("/v1/dimension", dependencies=[Depends(verify_cml_token)])
def get_dimension():
    return {"dimension": VECTOR_DIMENSION}


@app.post("/v1/embeddings", dependencies=[Depends(verify_cml_token)])
def generate_embeddings(payload: EmbedRequest):
    try:
        if isinstance(payload.input, str):
            vectors = embedder.encode(payload.input, show_progress_bar=False).tolist()
        else:
            vectors = embedder.encode(payload.input, show_progress_bar=False, batch_size=32).tolist()
        return {"embeddings": vectors, "dimension": VECTOR_DIMENSION}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding calculation error: {str(e)}")


@app.post("/v1/rerank", dependencies=[Depends(verify_cml_token)])
def rerank_documents(payload: RerankRequest):
    if not payload.documents:
        return {"results": []}

    try:
        pairs = [[payload.query, doc] for doc in payload.documents]
        scores = reranker.predict(pairs)

        results = [
            {"index": idx, "document": doc, "score": float(score)}
            for idx, (doc, score) in enumerate(zip(payload.documents, scores))
        ]
        results.sort(key=lambda x: x["score"], reverse=True)
        return {"results": results[:payload.top_n]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reranking execution error: {str(e)}")