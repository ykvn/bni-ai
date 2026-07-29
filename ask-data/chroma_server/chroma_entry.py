import os
import sys
import subprocess
from pathlib import Path
import uvicorn

# 🩹 ENTERPRISE LINUX RUNTIME PATCH: Force modern SQLite layers immediately
try:
    import pysqlite3  # type: ignore
    sys.modules["sqlite3"] = pysqlite3
except ImportError:
    pass

def resolve_chroma_server_dir() -> Path:
    """Robustly finds the chroma_server directory."""
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
    """Install dependencies for the ChromaDB server."""
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

def main() -> None:
    server_dir = resolve_chroma_server_dir()
    os.chdir(server_dir)

    env = os.environ.copy()
    ensure_dependencies(server_dir, env)

    # 💡 DEFERRED IMPORTS: Only load chromadb AFTER dependencies are guaranteed to exist
    from chromadb.config import Settings as ChromaDBSettings
    from chromadb.server.fastapi import FastAPI as ChromaFastAPI

    chroma_host = os.getenv("CHROMA_SERVER_HOST", "127.0.0.1")
    chroma_port = int(os.getenv("CDSW_APP_PORT", "8000"))
    chroma_persist_dir = os.getenv("CHROMA_PERSIST_DIR", "/home/cdsw/chroma_server/chroma_db")

    print(f"🚀 Starting ChromaDB Server...")
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

    app = ChromaFastAPI(chroma_settings)

    uvicorn.run(app, host=chroma_host, port=chroma_port)

if __name__ == "__main__":
    main()