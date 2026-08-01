import os
import sys
from typing import List, Tuple
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pydantic import BaseModel
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
import mlflow

# ⚡ CPU INFERENCE OPTIMIZATION LAYER
torch.set_num_threads(4)
torch.set_num_interop_threads(4)

# 🌐 CLOUDERA AI REGISTRY CONFIGURATION
REGISTRY_MODEL_NAME = os.environ.get("CML_MODEL_NAME", "qwen-cpu-model")
REGISTRY_MODEL_VERSION = os.environ.get("CML_MODEL_VERSION", "1")  # e.g., "1", "2", or "Production"

# 📌 Global metadata tracker
model_metadata = {
    "source": "UNINITIALIZED",
    "path": "N/A"
}

def resolve_model_path() -> Tuple[str, str]:
    """
    Downloads model artifacts from Cloudera AI Registry (MLflow).
    Falls back to local NFS directories if registry access is unavailable.
    Returns: (model_path, source_type)
    """
    # 1. Try Cloudera AI Registry
    try:
        model_uri = f"models:/{REGISTRY_MODEL_NAME}/{REGISTRY_MODEL_VERSION}"
        print(f"📡 [MODEL RESOLVER] Attempting fetch from Cloudera AI Registry: '{model_uri}'...")
        
        downloaded_path = mlflow.artifacts.download_artifacts(artifact_uri=model_uri)
        
        if os.path.isdir(downloaded_path):
            return downloaded_path, "CLOUDERA_AI_REGISTRY"
    except Exception as err:
        print(f"⚠️ [MODEL RESOLVER] Could not download from Cloudera AI Registry: {err}")
        print("🔍 [MODEL RESOLVER] Falling back to local NFS / disk storage...")

    # 2. Local NFS / Filesystem Fallback
    base_cwd = os.getcwd()
    script_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else base_cwd
    parent_dir = os.path.dirname(script_dir)

    candidate_paths = [
        os.path.join(base_cwd, "model_weights_cpu"),
        os.path.join(base_cwd, "ask-data", "qwen_inference", "model_weights_cpu"),
        os.path.join(base_cwd, "qwen_inference", "model_weights_cpu"),
        os.path.join(parent_dir, "model_weights_cpu")
    ]

    local_path = next((p for p in candidate_paths if os.path.isdir(p) and "config.json" in os.listdir(p)), None)
    if not local_path:
        print(f"❌ [CRITICAL ERROR] Could not locate model weights in Registry or Local NFS at: {candidate_paths}")
        sys.exit(1)

    return local_path, "LOCAL_NFS_STORAGE"


global_model = None
global_tokenizer = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global global_model, global_tokenizer, model_metadata
    
    # Resolve path and source
    path, source = resolve_model_path()
    model_metadata["source"] = source
    model_metadata["path"] = path

    # 🌟 PROMINENT TERMINAL BANNER REMARK
    print("\n" + "="*70)
    if source == "CLOUDERA_AI_REGISTRY":
        print("🚀 [MODEL SOURCE REMARK]: Loaded directly from CLOUDERA AI REGISTRY!")
        print(f"   Model URI : models:/{REGISTRY_MODEL_NAME}/{REGISTRY_MODEL_VERSION}")
        print(f"   Cache Path: {path}")
    else:
        print("📁 [MODEL SOURCE REMARK]: Loaded from LOCAL NFS / FILESYSTEM STORAGE!")
        print(f"   Local Path: {path}")
    print("="*70 + "\n")

    print(f"⏳ Loading Qwen weights into CPU RAM...")
    global_tokenizer = AutoTokenizer.from_pretrained(path)
    global_model = AutoModelForCausalLM.from_pretrained(
        path,
        device_map="cpu",              
        dtype=torch.float32,           
        low_cpu_mem_usage=True
    )
    print("✅ Model successfully loaded and ready for inference.\n")
    
    yield  
    
    print("🧹 Shutting down and clearing RAM...")
    global_model = None
    global_tokenizer = None


app = FastAPI(title="Qwen CPU OpenAI-Aligned Inference Engine", lifespan=lifespan)

class ChatMessage(BaseModel):
    role: str
    content: str

class OpenAIPayload(BaseModel):
    model: str
    messages: List[ChatMessage]
    temperature: float = 0.0

@app.post("/v1/chat/completions")
def generate_sql_on_cpu(payload: OpenAIPayload):
    system_prompt = next((msg.content for msg in payload.messages if msg.role == "system"), "")
    user_question = next((msg.content for msg in payload.messages if msg.role == "user"), "")

    formatted_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_question}
    ]
    
    text = global_tokenizer.apply_chat_template(formatted_messages, tokenize=False, add_generation_prompt=True)
    model_inputs = global_tokenizer([text], return_tensors="pt").to("cpu")
    
    with torch.no_grad():
        generated_ids = global_model.generate(
            **model_inputs,
            max_new_tokens=256,
            temperature=0.1,
            do_sample=False
        )
    
    generated_ids = [output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)]
    response = global_tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
    
    return {
        "choices": [{"message": {"role": "assistant", "content": response.strip()}}]
    }

@app.get("/")
def health_check():
    """Satisfies CML health checks AND provides explicit model origin metadata."""
    return {
        "status": "healthy",
        "model_engine": "Qwen CPU Inference Engine",
        "model_source_remark": model_metadata["source"],
        "resolved_model_path": model_metadata["path"]
    }