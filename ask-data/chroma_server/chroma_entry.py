"""
CAI / CML Application entry point for ChromaDB HTTP Server.

Setup in CAI / CML Application:
  Name    : chroma
  Script  : ask-data/chroma_server/chroma_entry.py
"""

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

# Global config: load the single ask-data/.env BEFORE any service code reads env vars.
_ASK_DATA_ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

import shared.config_loader as config_loader
config_loader.bootstrap(hint=_ASK_DATA_ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def resolve_port() -> int:
    """Resolves the active port assigned by CML."""
    for var in ["CDSW_APP_PORT", "PORT", "CDSW_PUBLIC_PORT"]:
        logging.info("ENV %s = %s", var, os.getenv(var, "(not set)"))
    raw = os.getenv("CDSW_APP_PORT") or os.getenv("PORT") or "8080"
    try:
        return int(raw)
    except ValueError:
        return 8080


def resolve_data_path() -> str:
    """Resolves and ensures the ChromaDB persistence folder on disk."""
    default = "/home/cdsw/ask-data/chroma_server/chroma_db"
    path = os.getenv("CHROMA_DATA_PATH", default).strip()

    if not os.path.isabs(path):
        path = os.path.abspath(os.path.join("/home/cdsw", path.lstrip("/")))

    Path(path).mkdir(parents=True, exist_ok=True)
    return path


def ensure_chromadb() -> None:
    """Ensures chromadb is installed in the current environment."""
    try:
        import chromadb  # noqa: F401
        logging.info("chromadb %s already installed", chromadb.__version__)
    except ImportError:
        logging.info("Installing chromadb...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "chromadb>=0.4.0"], check=True)


# 1. Validate environment dependencies
ensure_chromadb()

import chromadb

port = resolve_port()
data_path = resolve_data_path()
host = "127.0.0.1"  # Bound explicitly to loopback for CML Ingress Proxy

logging.info("chromadb version : %s", chromadb.__version__)
logging.info("Host             : %s", host)
logging.info("Port             : %s", port)
logging.info("Data path        : %s", data_path)

# 2. Run initial server dependency test
logging.info("=== TESTING ChromaDB Server Dependencies ===")
test_script = f"""
import sys, os, traceback
os.environ['ANONYMIZED_TELEMETRY'] = 'FALSE'
try:
    import uvicorn
    from chromadb.config import Settings
    from chromadb.server.fastapi import FastAPI as ChromaFastAPI
    settings = Settings(is_persistent=True, persist_directory='{data_path}', allow_reset=False, anonymized_telemetry=False)
    server = ChromaFastAPI(settings)
    app = server.app()
    print("ALL OK", flush=True)
except Exception as e:
    traceback.print_exc()
    sys.exit(1)
"""
result = subprocess.run([sys.executable, "-c", test_script], capture_output=True, text=True, timeout=30)
logging.info("Test STDOUT: %s", result.stdout.strip())
if result.stderr:
    logging.info("Test STDERR: %s", result.stderr.strip())

if result.returncode != 0:
    logging.warning("Subprocess missing dependencies — attempting automatic repair...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                    "opentelemetry-api", "opentelemetry-sdk",
                    "opentelemetry-instrumentation-fastapi",
                    "uvicorn[standard]"], check=False)

logging.info("=== STARTING CHROMADB SERVER ===")

api_script = f"""
import os
import uvicorn
from chromadb.config import Settings
from chromadb.server.fastapi import FastAPI as ChromaFastAPI

settings = Settings(
    is_persistent=True,
    persist_directory='{data_path}',
    allow_reset=False,
    anonymized_telemetry=False,
    chroma_server_http_port={port},
    chroma_server_host='{host}',
)

server = ChromaFastAPI(settings)
asgi_app = server.app()

uvicorn.run(asgi_app, host='{host}', port={port}, log_level='info')
"""

env = {
    **os.environ, 
    "ANONYMIZED_TELEMETRY": "FALSE",
    "IS_PERSISTENT": "TRUE",
    "PERSIST_DIRECTORY": data_path,
    "ALLOW_RESET": "FALSE",
    "CHROMA_SERVER_HTTP_PORT": str(port),
    "CHROMA_SERVER_HOST": host,
}


def start_proc():
    # Stream stderr directly to sys.stderr to prevent 64KB pipe buffer deadlocks
    return subprocess.Popen(
        [sys.executable, "-c", api_script],
        stdout=sys.stdout,
        stderr=sys.stderr,
        env=env,
        text=True,
    )


proc = start_proc()
logging.info("ChromaDB PID: %s", proc.pid)

time.sleep(5)

if proc.poll() is not None:
    logging.error("ChromaDB died immediately with exit code %s!", proc.returncode)
    raise RuntimeError(f"chromadb failed to start (exit code {proc.returncode})")

logging.info("✅ ChromaDB is actively listening on %s:%s", host, port)

# Keep-alive process monitoring loop
while True:
    ret = proc.poll()
    if ret is not None:
        logging.error("ChromaDB process exited unexpectedly (code %s). Restarting in 5s...", ret)
        time.sleep(5)
        proc = start_proc()
        logging.info("ChromaDB restarted, new PID: %s", proc.pid)
    time.sleep(2)