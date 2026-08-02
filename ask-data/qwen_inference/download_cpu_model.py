import os
from huggingface_hub import snapshot_download

def download_qwen_cpu_model():
    model_repo = "Qwen/Qwen2.5-3B-Instruct"
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    target_dir = os.path.join(current_dir, "model_weights_cpu")
    
    hf_token = os.getenv("HF_TOKEN")
    
    print(f"🚀 Initiating secure download stream for Smart Agent Model: {model_repo}")
    print(f"📂 Target destination: {target_dir}")
    
    try:
        model_path = snapshot_download(
            repo_id=model_repo,
            local_dir=target_dir,
            local_dir_use_symlinks=False,
            ignore_patterns=["*.msgpack", "*.h5"],
            max_workers=2,
            token=hf_token  
        )
        print(f"\n✅ 3B Model weights compiled successfully at: {model_path}")
        
    except Exception as e:
        print(f"\n❌ Error downloading model weights: {str(e)}")

if __name__ == "__main__":
    download_qwen_cpu_model()