import os
import sys
import subprocess
from pathlib import Path

# Suppress SSL certificate verification warnings in enterprise CML environments
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1. Resolve Root Directory
_ASK_DATA_ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

import shared.config_loader as config_loader
config_loader.bootstrap(hint=_ASK_DATA_ROOT)


# 2. Resolve Service Directory safely (notebook/session safe)
def _resolve_frontend_dir() -> Path:
    candidates = []
    if "__file__" in globals():
        current_file = Path(__file__).resolve()
        candidates.extend([current_file.parent, current_file.parent.parent])

    cwd = Path.cwd()
    candidates.extend([
        cwd, cwd / "frontend", cwd / "ask-data" / "frontend",
        cwd / "ask-data", Path("/home/cdsw/ask-data/frontend"),
        Path("/home/cdsw/frontend"), Path("/home/cdsw"),
    ])

    for candidate in candidates:
        candidate_path = candidate.resolve() if hasattr(candidate, "resolve") else Path(candidate)
        if (candidate_path / "app" / "main.py").exists():
            return candidate_path

    if "__file__" in globals():
        return Path(__file__).resolve().parent
    return cwd


FRONTEND_DIR = _resolve_frontend_dir()
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))


def ensure_dependencies(frontend_dir: Path, env: dict) -> None:
    req_file = frontend_dir / "requirements.txt"
    if not req_file.exists():
        return

    print(f"📦 Validating frontend dependencies from {req_file}...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"],
        check=True, env=env,
    )


def main() -> None:
    frontend_dir = _resolve_frontend_dir()
    os.chdir(frontend_dir)
    env = os.environ.copy()
    
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{frontend_dir}:{_ASK_DATA_ROOT}:{pythonpath}" if pythonpath else f"{frontend_dir}:{_ASK_DATA_ROOT}"
    
    ensure_dependencies(frontend_dir, env)
    
    # Import main application after environment paths and dependencies are verified
    from app.main import build_ui
    
    demo = build_ui()
    port = int(os.environ.get("CDSW_APP_PORT", 8080))
    print(f"🌐 [CML Frontend App] Starting Gradio UI Engine on http://127.0.0.1:{port}")
    demo.launch(server_name="127.0.0.1", server_port=port, share=False)


if __name__ == "__main__":
    main()