import os
import sys
import subprocess
from pathlib import Path

_ASK_DATA_ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

import shared.config_loader as config_loader
config_loader.bootstrap(hint=_ASK_DATA_ROOT)

def _resolve_backend_dir() -> Path:
    return Path(__file__).resolve().parent

BACKEND_DIR = _resolve_backend_dir()
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.ingest_knowledge import build_ingest_config, run_auto_ingest

def ensure_dependencies(backend_dir: Path, env: dict) -> None:
    req_file = backend_dir / "requirements.txt"
    if req_file.exists():
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"], check=True, env=env)

def trigger_rag_auto_ingest(backend_dir: Path, env: dict | None = None) -> None:
    try:
        config = build_ingest_config(backend_dir=backend_dir, env=env)
        run_auto_ingest(
            docs_dir=config["docs_dir"],
            qdrant_server_url=config["qdrant_server_url"],
            qdrant_ssl=config["qdrant_ssl"],
            collection_name=config["collection_name"],
            embedding_model_name=config.get("embedding_model_name", "all-MiniLM-L6-v2"),
            cml_token=config.get("cml_token"),
        )
    except Exception as e:
        print(f"⚠️ [RAG STARTUP WARNING] Bypass: {str(e)}")

def main() -> None:
    backend_dir = _resolve_backend_dir()
    os.chdir(backend_dir)
    app_port = int(os.environ.get("CDSW_APP_PORT", 8090))
    
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{backend_dir}:{pythonpath}" if pythonpath else str(backend_dir)
    
    ensure_dependencies(backend_dir, env)
    trigger_rag_auto_ingest(backend_dir, env=env)
    
    cmd = [
        sys.executable, "-m", "uvicorn", "app.main:app",       
        "--host", "127.0.0.1", "--port", str(app_port), "--log-level", "info"
    ]
    print(f"🌐 [CML APP 1] Gateway REST API running on http://127.0.0.1:{app_port}")
    process = subprocess.Popen(cmd, cwd=str(backend_dir), env=env)
    
    try:
        process.wait()
    except KeyboardInterrupt:
        process.terminate()

if __name__ == "__main__":
    main()