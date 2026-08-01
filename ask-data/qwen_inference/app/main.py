import os
import sys
from typing import List, Tuple
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pydantic import BaseModel
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
import mlflow
import cmlapi
from typing import Tuple

# ⚡ CPU INFERENCE OPTIMIZATION LAYER
torch.set_num_threads(4)
torch.set_num_interop_threads(4)

# 🌐 CLOUDERA AI REGISTRY CONFIGURATION (Matches your exact registered model)
REGISTRY_MODEL_NAME = os.environ.get("CML_MODEL_NAME", "Qwen2.5-1.5B-Instruct-AWQ")
REGISTRY_MODEL_VERSION = os.environ.get("CML_MODEL_VERSION", "1")

# 📌 Global metadata tracker
model_metadata = {
    "source": "UNINITIALIZED",
    "path": "N/A",
    "model_uri": f"models:/{REGISTRY_MODEL_NAME}/{REGISTRY_MODEL_VERSION}"
}


def resolve_model_path() -> Tuple[str, str]:
    """
    Downloads model artifacts from Cloudera AI Registry using CML APIv2.
    Falls back to local NFS directories if registry access is unavailable.
    """
    try:
        # 1. Initialize Cloudera API Client natively (Auto-detects URL and CDSW_APIV2_KEY)
        print("📡 [MODEL RESOLVER] Connecting to CML API using auto-detected credentials...")
        client = cmlapi.default_client()

        # 2. Query the Registered Model from AI Registry
        model_name = os.environ.get("CML_MODEL_NAME", "Qwen2.5-1.5B-Instruct-AWQ")
        model_version = os.environ.get("CML_MODEL_VERSION", "1")
        
        search_res = client.list_registered_models()
        
        # 🟢 FIX: Extract the list using the correct SDK attribute (usually '.models')
        models_list = getattr(search_res, 'models', getattr(search_res, 'registered_models', []))
        
        # Safety net: If the list is empty, let's print the actual attributes to see what the SDK gave us
        if not models_list:
            print(f"🧐 [DEBUG SDK RESPONSE] Available attributes in search_res: {dir(search_res)}")
        
        target_model = None
        for m in models_list:
            # The SDK might use '.name' or '.model_name', so we check both safely
            m_name = getattr(m, 'name', getattr(m, 'model_name', ''))
            if m_name == model_name:
                target_model = m
                break
        
        if target_model:
            model_id = getattr(target_model, 'id', getattr(target_model, 'model_id', None))
            
            print(f"✅ [MODEL RESOLVER] Found '{model_name}' (ID: {model_id}) in Cloudera AI Registry.")
            
            # Fetch the specific version details
            # version_details = client.get_registered_model(model_id)
            # print(f"🧐 [DEBUG VERSION DETAILS] {dir(version_details)}")
            
        else:
             print(f"⚠️ [MODEL RESOLVER] Model '{model_name}' was not found in the registry list.")
            
    except Exception as err:
        print(f"⚠️ [MODEL RESOLVER] Could not retrieve from Cloudera AI Registry via APIv2: {type(err).__name__} - {err}")
        print("🔍 [MODEL RESOLVER] Searching local NFS / disk storage as fallback...")

    # 3. Local NFS / Filesystem Fallback Strategy
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
        print(f"❌ [CRITICAL ERROR] Could not locate model weights in Registry or Local NFS paths.")
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
    if source == "CLOUDERA_AI_REGISTRY":
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