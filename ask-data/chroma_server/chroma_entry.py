import os
import sys
import subprocess
from pathlib import Path

# 🩹 SAFE LOG BUFFERING: Gracefully handles both standard Python runtime & IPython OutStream
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass


def resolve_chroma_server_dir() -> Path:
    """Robustly locates the chroma_server directory across CML execution paths."""
    cwd = Path.cwd()
    candidates = [
        Path(__file__).parent.resolve() if '__file__' in globals() else cwd,
        cwd / "chroma_server",
        cwd / "ask-data" / "chroma_server",
        Path("/home/cdsw/ask-data/chroma_server")
    ]
    for c in candidates:
        if (c / "chroma_entry.py").exists():
            return c
    print(f"❌ CRITICAL SETUP ERROR: Could not locate 'chroma_server' directory.")
    sys.exit(1)


def ensure_dependencies(server_dir: Path, env: dict) -> None:
    """Validates and installs requirements.txt directly into the CML runtime."""
    req_file = server_dir / "requirements.txt"
    if not req_file.exists():
        print(f"⚠️ No requirements.txt found at {req_file}. Skipping dependency installation.")
        return

    print(f"📦 Validating ChromaDB server dependencies from {req_file}...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"],
            check=True,
            env=env,
        )
        print("✅ ChromaDB server dependencies verified successfully.")
    except subprocess.CalledProcessError as e:
        print(f"❌ Critical Error: Failed to configure ChromaDB server dependencies: {str(e)}")
        sys.exit(1)


def run_chroma_worker() -> None:
    """
    CML WORKER PROCESS: Instantiates SQLite patches and runs 
    the programmatic ChromaFastAPI server.
    """
    # 🩹 ENTERPRISE LINUX RUNTIME PATCH: Force modern SQLite layers immediately
    try:
        import pysqlite3  # type: ignore
        sys.modules["sqlite3"] = pysqlite3
    except ImportError:
        pass

    import uvicorn
    from chromadb.config import Settings as ChromaDBSettings
    from chromadb.server.fastapi import FastAPI as ChromaFastAPI

    chroma_host = os.getenv("CHROMA_SERVER_HOST", "127.0.0.1")
    chroma_port = int(os.getenv("CDSW_APP_PORT", "8000"))
    chroma_persist_dir = os.getenv("CHROMA_PERSIST_DIR", "/home/cdsw/chroma_server/chroma_db")

    # Ensure persist folder exists
    Path(chroma_persist_dir).mkdir(parents=True, exist_ok=True)

    print(f"🚀 Starting Programmatic ChromaDB FastAPI Server...")
    print(f"🌐 Host: {chroma_host}, Port: {chroma_port}")
    print(f"💾 Persistence Directory: {chroma_persist_dir}")

    chroma_settings = ChromaDBSettings(
        chroma_api_impl="chromadb.api.fastapi.FastAPI",
        chroma_server_host=chroma_host,
        chroma_server_http_port=chroma_port,
        is_persistent=True,
        persist_directory=chroma_persist_dir,
        allow_reset=True
    )

    # 🔧 FIX: Extract the underlying ASGI application from ChromaFastAPI
    server = ChromaFastAPI(chroma_settings)
    app = server.app() if callable(getattr(server, "app", None)) else getattr(server, "_app", server)

    # Launch uvicorn
    uvicorn.run(app, host=chroma_host, port=chroma_port)


def main() -> None:
    # 0. Check if this invocation is the worker process
    if "--worker" in sys.argv:
        run_chroma_worker()
        return

    # 1. Lock in the target directory context
    server_dir = resolve_chroma_server_dir()
    os.chdir(server_dir)

    # 2. Inject environment settings
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{server_dir}:{pythonpath}" if pythonpath else str(server_dir)
    env["PYTHONUNBUFFERED"] = "1"

    # 3. Verify required dependencies
    ensure_dependencies(server_dir, env)

    # 4. Check for CML Application Port
    if "CDSW_APP_PORT" not in os.environ:
        print("⚠️ WARNING: 'CDSW_APP_PORT' is missing. Defaulting port to 8000.")
        env["CDSW_APP_PORT"] = "8000"

    entry_script = server_dir / "chroma_entry.py"
    cmd = [sys.executable, str(entry_script), "--worker"]

    app_port = env.get("CDSW_APP_PORT")
    chroma_host = env.get("CHROMA_SERVER_HOST", "127.0.0.1")

    print(f"\n📡 Launching CML ChromaDB Application Gateway...")
    print(f"🌐 Network Bound: http://{chroma_host}:{app_port}")

    process = subprocess.Popen(cmd, cwd=str(server_dir), env=env)

    try:
        process.wait()
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 CML Application stop signal received. Shutting down ChromaDB...")
        process.terminate()
        process.wait()


if __name__ == "__main__":
    main()