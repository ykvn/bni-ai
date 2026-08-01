# ask-data/qwen_inference/qwen_entry.py
import os
import sys
import subprocess
import time
from pathlib import Path

# 🎯 Global config: load the single ask-data/.env BEFORE any service code reads env vars.
_ASK_DATA_ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

import shared.config_loader as config_loader
config_loader.bootstrap(hint=_ASK_DATA_ROOT)

from download_model import download_qwen_model

def ensure_vllm_dependencies():
    """Ensures the core GPU acceleration and huggingface libraries are ready"""
    print("📦 Validating vLLM engine dependencies...")
    # We install vllm and huggingface_hub explicitly for the GPU container
    packages = ["vllm==0.6.3", "huggingface_hub", "pip", "setuptools"]
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", *packages])
        print("✅ Inference engines compiled and up to date.")
    except Exception as e:
        print(f"❌ Dependency installation failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    # 1. Coordinate file paths cleanly inside Cloudera
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    # 2. Automatically self-heal the environment libraries
    ensure_vllm_dependencies()
    
    # 3. Automatically download the Qwen-14B weights if not present
    # This runs your download_model.py logic safely
    weight_path = os.path.join(script_dir, "model_weights")
    if not os.path.exists(weight_path) or len(os.listdir(weight_path)) < 5:
        download_qwen_model()
    else:
        print("💾 Found existing verified Qwen2.5-AWQ weights on disk. Skipping download step.")

    # 4. Fetch Cloudera's assigned networking parameters
    app_port = os.getenv("CDSW_APP_PORT", "8001")
    print(f"🌐 Provisioning OpenAI-Compatible vLLM Server on localhost:{app_port}")

    # 5. Launch the high-performance vLLM engine as the primary application process
    # We pass 'localhost' as host binding to respect your enterprise proxy network layout
    vllm_cmd = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--model", "./model_weights",
        "--quantization", "awq",
        "--host", "localhost",
        "--port", str(app_port),
        "--max-model-len", "4096"
    ]

    print(f"🚀 Executing process command: {' '.join(vllm_cmd)}")
    
    # Run vllm as a blocking system call so the Cloudera Application stays alive
    process = subprocess.Popen(vllm_cmd)
    
    try:
        process.wait()
    except KeyboardInterrupt:
        print("🛑 Shutting down model inference server...")
        process.terminate()