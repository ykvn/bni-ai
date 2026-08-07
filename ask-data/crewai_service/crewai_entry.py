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
def _resolve_crewai_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    return _ASK_DATA_ROOT / "crewai_service"


CREWAI_DIR = _resolve_crewai_dir()
if str(CREWAI_DIR) not in sys.path:
    sys.path.insert(0, str(CREWAI_DIR))

try:
    from crewai_service.app.worker import run_worker_loop, is_policy_question, _build_payload  # noqa: F401
except ImportError:
    pass


def ensure_dependencies(crewai_dir: Path, env: dict) -> None:
    req_file = crewai_dir / "requirements.txt"
    if req_file.exists():
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"], check=True, env=env)


def main() -> None:
    crewai_dir = _resolve_crewai_dir()
    os.chdir(crewai_dir)
    app_port = int(os.environ.get("CDSW_APP_PORT", 8091))
    
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{crewai_dir}:{_ASK_DATA_ROOT}:{pythonpath}" if pythonpath else f"{crewai_dir}:{_ASK_DATA_ROOT}"
    
    ensure_dependencies(crewai_dir, env)
    
    cmd = [
        sys.executable, "-m", "uvicorn", "app.main:app",       
        "--host", "127.0.0.1", "--port", str(app_port), "--log-level", "warning"
    ]
    print(f"🌐 [CML CrewAI Engine] Service REST API running on http://127.0.0.1:{app_port}")
    process = subprocess.Popen(cmd, cwd=str(crewai_dir), env=env)
    
    try:
        process.wait()
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Shutting down CrewAI Service...")
        process.terminate()


if __name__ == "__main__":
    main()