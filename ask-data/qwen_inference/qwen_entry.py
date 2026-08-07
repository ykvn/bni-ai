"""
CAI / CML Application entry point for the Qwen Inference vLLM Server.
"""
import os
import sys
import subprocess
from pathlib import Path

# Ensure ask-data/ root is importable before importing shared.*
_ASK_DATA_ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

from shared.entry_utils import bootstrap_service, resolve_service_dir, resolve_port

_SERVICE_NAME = "qwen_inference"
_CALLER_FILE = __file__ if "__file__" in globals() else None


def ensure_vllm_dependencies():
    """Ensures the core GPU acceleration and huggingface libraries are ready."""
    print("📦 Validating vLLM engine dependencies...")
    packages = ["vllm==0.6.3", "huggingface_hub", "pip", "setuptools"]
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", *packages])
        print("✅ Inference engines compiled and up to date.")
    except Exception as e:
        print(f"❌ Dependency installation failed: {str(e)}")
        sys.exit(1)


def main() -> None:
    ask_data_root = bootstrap_service(_SERVICE_NAME)
    script_dir = resolve_service_dir(_SERVICE_NAME, ask_data_root, caller_file=_CALLER_FILE)

    # Ensure the service directory is importable in this process (CML runs from here)
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    # 1. Coordinate file paths cleanly inside Cloudera
    os.chdir(script_dir)

    # 2. Automatically self-heal the environment libraries
    ensure_vllm_dependencies()

    # 3. Automatically download the Qwen-14B weights if not present
    from download_model import download_qwen_model

    weight_path = os.path.join(script_dir, "model_weights")
    if not os.path.exists(weight_path) or len(os.listdir(weight_path)) < 5:
        download_qwen_model()
    else:
        print("💾 Found existing verified Qwen2.5-AWQ weights on disk. Skipping download step.")

    # 4. Fetch Cloudera's assigned networking parameters
    app_port = resolve_port(default=8001)
    print(f"🌐 Provisioning OpenAI-Compatible vLLM Server on localhost:{app_port}")

    # 5. Launch the high-performance vLLM engine as the primary application process
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


if __name__ == "__main__":
    main()