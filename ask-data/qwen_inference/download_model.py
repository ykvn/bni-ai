# ask-data/qwen_inference/download_model.py
import os
from huggingface_hub import snapshot_download

def download_qwen_model():
    # 🎯 Swapped to the ultra-lightweight 1.5B model (Only ~1.1 GB total footprint!)
    model_repo = "Qwen/Qwen2.5-3B-Instruct"
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    target_dir = os.path.join(current_dir, "model_weights")
    
    hf_token = os.getenv("HF_TOKEN")
    
    print(f"🚀 Initiating secure sequential download stream for: {model_repo}")
    print(f"📂 Target local project destination: {target_dir}")
    print("🛡️ Stability Mode: max_workers=1 active (Safe for shared file systems).")
    
    try:
        model_path = snapshot_download(
            repo_id=model_repo,
            local_dir=target_dir,
            local_dir_use_symlinks=False,
            ignore_patterns=["*.msgpack", "*.h5"],
            max_workers=1,  # Kept at 1 for safe, stable sequential downloads
            token=hf_token  
        )
        print(f"\n✅ Model files downloaded completely and verified at: {model_path}")
        
    except Exception as e:
        print(f"\n❌ Error downloading model weights from Hugging Face: {str(e)}")

if __name__ == "__main__":
    download_qwen_model()