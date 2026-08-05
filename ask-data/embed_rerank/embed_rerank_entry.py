import os
import sys
import subprocess
from pathlib import Path

# 1. Resolve Root Directory & Load Global .env Config
_ASK_DATA_ROOT = Path(__file__).resolve().parent if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

import shared.config_loader as config_loader
config_loader.bootstrap(hint=_ASK_DATA_ROOT)


# 2. Resolve Service Directory
def _resolve_embed_rerank_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent / "embed_rerank"
    return _ASK_DATA_ROOT / "embed_rerank"


SERVICE_DIR = _resolve_embed_rerank_dir()
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))


def main() -> None:
    app_port = int(os.environ.get("CDSW_APP_PORT", 8090))
    
    # Ensure PYTHONPATH includes root and service directories
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{SERVICE_DIR}:{_ASK_DATA_ROOT}:{pythonpath}" if pythonpath else f"{SERVICE_DIR}:{_ASK_DATA_ROOT}"

    print(f"📡 [embed-rerank Launcher] Starting FastAPI REST Engine on http://127.0.0.1:{app_port}", flush=True)

    # Launch Uvicorn server pointing to embed_rerank.app.main:app
    api_cmd = [
        sys.executable, "-m", "uvicorn", "embed_rerank.app.main:app",
        "--host", "127.0.0.1",
        "--port", str(app_port),
        "--log-level", "info"
    ]

    process = subprocess.Popen(api_cmd, cwd=str(_ASK_DATA_ROOT), env=env)

    try:
        process.wait()
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Shutting down embed-rerank Service...")
    finally:
        if process.poll() is None:
            print("🧹 Terminating Uvicorn process...")
            process.terminate()


if __name__ == "__main__":
    main()