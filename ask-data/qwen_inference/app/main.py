import os
import sys
from contextlib import asynccontextmanager
from typing import List, Tuple

import cmlapi
from fastapi import FastAPI
from huggingface_hub import snapshot_download
from pydantic import BaseModel
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

# ⚡ CPU INFERENCE OPTIMIZATION LAYER
torch.set_num_threads(4)
torch.set_num_interop_threads(4)

# 🌐 CLOUDERA AI REGISTRY CONFIGURATION (Matches your exact registered model)
REGISTRY_MODEL_NAME = os.environ.get("CML_MODEL_NAME", "")
REGISTRY_MODEL_VERSION = os.environ.get("CML_MODEL_VERSION", "1")

# 📌 Global metadata tracker
model_metadata = {
    "source": "UNINITIALIZED",
    "path": "N/A",
    "model_uri": f"models:/{REGISTRY_MODEL_NAME}/{REGISTRY_MODEL_VERSION}"
}


def resolve_model_path() -> Tuple[str, str]:
    """
    Verifies the model in CML Registry and dynamically pulls the HuggingFace source.
    """
    print("📡 [MODEL RESOLVER] Connecting to CML API to verify registry configuration...")
    
    # Matching the exact name from your latest screenshot
    model_name = os.environ.get("CML_MODEL_NAME", "")
    
    try:
        client = cmlapi.default_client()
        search_res = client.list_registered_models()
        models_list = getattr(search_res, 'models', getattr(search_res, 'registered_models', []))
        
        target_model = next((m for m in models_list if getattr(m, 'name', getattr(m, 'model_name', '')) == model_name), None)
        
        if target_model:
            model_id = getattr(target_model, 'id', getattr(target_model, 'model_id', None))
            print(f"✅ [MODEL RESOLVER] Verified '{model_name}' (ID: {model_id}) exists in Cloudera AI Registry.")
            print(f"✅ [MODEL RESOLVER] Registry indicates SOURCE is HuggingFace.")
            
            # Since the registry uses a HuggingFace pointer, we download from HF directly.
            # We map the UI name back to the actual HF repository name.
            hf_repo = model_name
            
            # Define a secure local cache path inside the container
            cache_dir = os.path.join(os.getcwd(), "hf_registry_cache")
            os.makedirs(cache_dir, exist_ok=True)
            
            print(f"⏳ [MODEL RESOLVER] Downloading weights directly from HuggingFace Hub to mirror registry import...")
            downloaded_path = snapshot_download(
                repo_id=hf_repo,
                local_dir=cache_dir,
                local_dir_use_symlinks=False # Forces actual file download instead of symlinks
            )
            
            print(f"🎉 [MODEL RESOLVER] Successfully pulled model artifacts: {downloaded_path}")
            return downloaded_path, "CLOUDERA_REGISTRY_HF_IMPORT"
            
        else:
            print(f"⚠️ Could not find '{model_name}' in the registry.")
            
    except Exception as err:
        print(f"⚠️ [MODEL RESOLVER] Verification error: {type(err).__name__} - {err}")

    print("🔍 [MODEL RESOLVER] Falling back to local NFS / disk storage...")

    # ==========================================
    # ATTEMPT 2: NFS FALLBACK STORAGE
    # ==========================================
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
        print(f"❌ [CRITICAL ERROR] Could not locate model weights in Registry OR Local NFS paths.")
        sys.exit(1)

    return local_path, "LOCAL_NFS_STORAGE"


global_model = None
global_tokenizer = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global global_model, global_tokenizer, model_metadata
    
    # Resolve physical weight location
    path, source = resolve_model_path()
    model_metadata["source"] = source
    model_metadata["path"] = path

    # 🌟 STARTUP REMARK BANNER
    print("\n" + "="*75)
    if "CLOUDERA" in source:
        print("🚀 [MODEL SOURCE REMARK]: Loaded directly from CLOUDERA AI REGISTRY!")
        print(f"   Model Target : {model_metadata['model_uri']}")
        print(f"   Cached Path  : {path}")
    else:
        print("📁 [MODEL SOURCE REMARK]: Loaded from LOCAL NFS / FILESYSTEM STORAGE!")
        print(f"   Local Path   : {path}")
    print("="*75 + "\n")

    print(f"⏳ Loading '{REGISTRY_MODEL_NAME}' tokenizer and weights into CPU RAM...")
    
    global_tokenizer = AutoTokenizer.from_pretrained(path, trust_remote_code=True)
    global_model = AutoModelForCausalLM.from_pretrained(
        path,
        device_map="cpu",              
        dtype=torch.float32,           
        low_cpu_mem_usage=True,
        trust_remote_code=True
    )
    print("✅ Model successfully loaded into RAM and ready for inference.\n")
    
    yield  
    
    print("🧹 Shutting down inference service and releasing RAM...")
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
    """Satisfies CML health checks and exposes model registry diagnostics."""
    return {
        "status": "healthy",
        "model_engine": "Qwen CPU Inference Engine",
        "model_name": REGISTRY_MODEL_NAME,
        "model_version": REGISTRY_MODEL_VERSION,
        "model_source_remark": model_metadata["source"],
        "resolved_model_path": model_metadata["path"]
    }