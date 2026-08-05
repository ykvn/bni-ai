import os
import sys
from contextlib import asynccontextmanager
from typing import List, Optional, Union, Tuple

import cmlapi
from fastapi import FastAPI, Header, HTTPException, Depends, status
from huggingface_hub import snapshot_download
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer, CrossEncoder

# ---------------------------------------------------------------------
# Global Model State
# ---------------------------------------------------------------------
embedder = None
reranker = None
VECTOR_DIMENSION = 0

model_metadata = {
    "embed_model": {
        "name": os.getenv("EMBEDDING_MODEL_NAME", ""),
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
# Registry Auto-Download Resolver
# ---------------------------------------------------------------------
def resolve_model_path(model_name: str) -> Tuple[str, str]:
    """
    Verifies the model in CML Registry and dynamically pulls the HuggingFace source[cite: 11].
    Falls back to direct HuggingFace download if not found in the registry.
    """
    print(f"📡 [MODEL RESOLVER] Connecting to CML API to verify registry for '{model_name}'...")
    
    try:
        client = cmlapi.default_client()
        search_res = client.list_registered_models()
        models_list = getattr(search_res, 'models', getattr(search_res, 'registered_models', []))
        
        target_model = next((m for m in models_list if getattr(m, 'name', getattr(m, 'model_name', '')) == model_name), None)
        
        if target_model:
            model_id = getattr(target_model, 'id', getattr(target_model, 'model_id', None))
            print(f"✅ [MODEL RESOLVER] Verified '{model_name}' (ID: {model_id}) exists in Cloudera AI Registry[cite: 11].")
            
            cache_dir = os.path.join(os.getcwd(), "hf_registry_cache", model_name.replace("/", "_"))
            os.makedirs(cache_dir, exist_ok=True)
            
            print(f"⏳ [MODEL RESOLVER] Downloading weights directly from HuggingFace Hub to mirror registry import...[cite: 11]")
            downloaded_path = snapshot_download(
                repo_id=model_name,
                local_dir=cache_dir,
                local_dir_use_symlinks=False
            )
            
            print(f"🎉 [MODEL RESOLVER] Successfully pulled model artifacts: {downloaded_path}[cite: 11]")
            return downloaded_path, "CLOUDERA_REGISTRY_HF_IMPORT"
            
        else:
            print(f"⚠️ Could not find '{model_name}' in the registry. Falling back to direct HuggingFace load.")
            
    except Exception as err:
        print(f"⚠️ [MODEL RESOLVER] Verification error: {type(err).__name__} - {err}. Falling back to direct HuggingFace load.")

    # SentenceTransformers natively handles direct HF Hub downloads if passed a standard repo ID.
    return model_name, "HUGGINGFACE_HUB_DIRECT"


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
    expected_token = os.getenv("CML_TOKEN") or os.getenv("CDSW_API_KEY")
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
@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "embed-rerank",
        "embedding_model": model_metadata["embed_model"],
        "reranker_model": model_metadata["rerank_model"],
        "vector_dimension": VECTOR_DIMENSION
    }


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