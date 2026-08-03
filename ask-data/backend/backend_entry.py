import os
import sys
import subprocess
from pathlib import Path

# Global config: load the single ask-data/.env BEFORE any service code reads env vars.
_ASK_DATA_ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

import shared.config_loader as config_loader
config_loader.bootstrap(hint=_ASK_DATA_ROOT)


def _resolve_backend_dir() -> Path:
    """Resolve the backend root whether the file is executed as a script or imported in a notebook."""
    candidates = []

    if "__file__" in globals():
        candidates.append(Path(__file__).resolve().parent)

    cwd = Path.cwd()
    candidates.extend([
        cwd,
        cwd / "backend",
        cwd / "ask-data" / "backend",
        cwd / "ask-data",
        Path("/home/cdsw/ask-data/backend"),
    ])

    for candidate in candidates:
        candidate_path = candidate.resolve() if hasattr(candidate, "resolve") else Path(candidate)
        if (candidate_path / "app" / "__init__.py").exists() or (candidate_path / "app" / "main.py").exists():
            return candidate_path

    if "__file__" in globals():
        return Path(__file__).resolve().parent
    return cwd


BACKEND_DIR = _resolve_backend_dir()
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.ingest_knowledge import build_ingest_config, run_auto_ingest


def ensure_dependencies(backend_dir: Path, env: dict) -> None:
    """
    Validates and installs packages from requirements.txt directly 
    into the CML application container runtime environment.
    """
    req_file = backend_dir / "requirements.txt"
    if not req_file.exists():
        print(f"⚠️ No requirements.txt found at {req_file}. Skipping dependency installation.")
        return
        
    print(f"📦 Validating dependencies from {req_file}...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"],
            check=True,
            env=env,
        )
        print("✅ Dependencies verified successfully.")
    except subprocess.CalledProcessError as e:
        print(f"❌ Critical Error: Failed to configure dependencies: {str(e)}")
        sys.exit(1)


def trigger_rag_auto_ingest(backend_dir: Path, env: dict | None = None) -> None:
    """Database Synchronization. Pre-populates Qdrant vector collection via Qdrant HTTP Endpoint."""
    print("\n📡 [RAG STARTUP] Synchronizing Knowledge Base document vector nodes...")
    try:
        if str(backend_dir) not in sys.path:
            sys.path.insert(0, str(backend_dir))

        config = build_ingest_config(backend_dir=backend_dir, env=env)
        print(f"[RAG STARTUP] Scanning file directory target: {config['docs_dir']}")
        print(f"[RAG STARTUP] Target Qdrant Endpoint: {config['qdrant_server_url']} (SSL: {config['qdrant_ssl']})")
        print(f"[RAG STARTUP] Target Collection: {config['collection_name']}")
        print(f"[RAG STARTUP] Embedding Model: {config.get('embedding_model_name', 'all-MiniLM-L6-v2')}")
        
        if config.get("cml_token"):
            print("[RAG STARTUP] CML Authentication: Token loaded for qdrant_server access.")

        # Pass Qdrant HTTP parameters + embedding model + CML authentication token
        run_auto_ingest(
            docs_dir=config["docs_dir"],
            qdrant_server_url=config["qdrant_server_url"],
            qdrant_ssl=config["qdrant_ssl"],
            collection_name=config["collection_name"],
            embedding_model_name=config.get("embedding_model_name", "all-MiniLM-L6-v2"),
            cml_token=config.get("cml_token"),
        )
        print("[RAG STARTUP] Document processing loop verified successfully.\n")

    except Exception as e:
        print(f"⚠️ [RAG STARTUP WARNING] Vector synchronization bypassed: {str(e)}\n")


def main() -> None:
    # 1. Lock execution environment down to the correct path context
    backend_dir = _resolve_backend_dir()
    os.chdir(backend_dir)
    
    # 2. Extract port specifications allocated dynamically by the environment
    app_port = int(os.environ.get("CDSW_APP_PORT", 8090))
    
    # 3. Patch environment variables with absolute PYTHONPATH variables
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{backend_dir}:{pythonpath}" if pythonpath else str(backend_dir)
    
    # 4. Process initialization sequence frameworks
    ensure_dependencies(backend_dir, env)
    trigger_rag_auto_ingest(backend_dir, env=env)
    
    # 5. Build standardized command execution pattern targeting app.main:app
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",       
        "--host",
        "127.0.0.1",
        "--port",
        str(app_port),
        "--log-level",
        "info"
    ]
    
    print(f"🌐 Starting Aligned Production Backend Server via subprocess on http://127.0.0.1:{app_port}")
    print(f"📍 Resolved Working Directory: {backend_dir}")
    
    # Launch Uvicorn safely in its own completely isolated process context
    process = subprocess.Popen(cmd, cwd=str(backend_dir), env=env)
    
    try:
        process.wait()
    except KeyboardInterrupt:
        print("\n🛑 Shutdown process triggered.")
    finally:
        print("🧹 Purging active production server execution sub-processes...")
        process.terminate()


if __name__ == "__main__":
    main()