"""
CAI / CML Application entry point for the Frontend Gradio UI.
"""
import os
import sys
from pathlib import Path

# Ensure ask-data/ root is importable before importing shared.*
_ASK_DATA_ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

# Suppress SSL certificate verification warnings in enterprise CML environments
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from shared.entry_utils import (
    bootstrap_service,
    resolve_service_dir,
    ensure_dependencies,
    build_pythonpath,
    resolve_port,
)

_SERVICE_NAME = "frontend"
_CALLER_FILE = __file__ if "__file__" in globals() else None


def main() -> None:
    ask_data_root = bootstrap_service(_SERVICE_NAME)
    frontend_dir = resolve_service_dir(_SERVICE_NAME, ask_data_root, caller_file=_CALLER_FILE)

    env = os.environ.copy()
    env["PYTHONPATH"] = build_pythonpath(frontend_dir, ask_data_root, env=env)

    ensure_dependencies(frontend_dir, env)

    # Import main application after environment paths and dependencies are verified
    from app.main import build_ui

    demo = build_ui()
    port = resolve_port(default=8080)
    print(f"🌐 [CML Frontend App] Starting Gradio UI Engine on http://127.0.0.1:{port}")
    demo.launch(server_name="127.0.0.1", server_port=port, share=False)


if __name__ == "__main__":
    main()