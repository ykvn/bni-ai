"""
CAI / CML Application entry point for the Backend Gateway REST API.
"""
import os
import sys
from pathlib import Path

# Ensure ask-data/ root is importable before importing shared.*
_ASK_DATA_ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

from shared.entry_utils import (
    bootstrap_service,
    resolve_service_dir,
    ensure_dependencies,
    build_pythonpath,
    launch_uvicorn,
    wait_for_process,
    resolve_port,
)

_SERVICE_NAME = "backend"
_CALLER_FILE = __file__ if "__file__" in globals() else None


def main() -> None:
    ask_data_root = bootstrap_service(_SERVICE_NAME)
    service_dir = resolve_service_dir(_SERVICE_NAME, ask_data_root, caller_file=_CALLER_FILE)

    # Ensure the service directory is importable in this process (CML runs from here)
    if str(service_dir) not in sys.path:
        sys.path.insert(0, str(service_dir))

    app_port = resolve_port(default=8090)

    env = os.environ.copy()
    env["PYTHONPATH"] = build_pythonpath(service_dir, env=env)

    ensure_dependencies(service_dir, env)

    process = launch_uvicorn(service_dir, "app.main:app", app_port, env)
    print(f"🌐 Backend REST API running on http://127.0.0.1:{app_port}")

    wait_for_process(process, _SERVICE_NAME)


if __name__ == "__main__":
    main()