import os
import sys
import subprocess
from pathlib import Path

# 1. Resolve Root Directory
_ASK_DATA_ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

import shared.config_loader as config_loader
config_loader.bootstrap(hint=_ASK_DATA_ROOT)


# 2. Resolve Service Directory safely (notebook/session safe)
def _resolve_backend_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    return _ASK_DATA_ROOT / "backend"


BACKEND_DIR = _resolve_backend_dir()
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def ensure_dependencies(backend_dir: Path, env: dict) -> None:
    req_file = backend_dir / "requirements.txt"
    if req_file.exists():
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"], check=True, env=env)


def main() -> None:
    backend_dir = _resolve_backend_dir()
    os.chdir(backend_dir)
    app_port = int(os.environ.get("CDSW_APP_PORT", 8090))
    
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{backend_dir}:{pythonpath}" if pythonpath else str(backend_dir)
    
    ensure_dependencies(backend_dir, env)
    
    cmd = [
        sys.executable, "-m", "uvicorn", "app.main:app",       
        "--host", "127.0.0.1", "--port", str(app_port), "--log-level", "warning"
    ]
    print(f"🌐 [CML APP 1] Gateway REST API running on http://127.0.0.1:{app_port}")
    process = subprocess.Popen(cmd, cwd=str(backend_dir), env=env)
    
    try:
        process.wait()
    except KeyboardInterrupt:
        process.terminate()


if __name__ == "__main__":
    main()