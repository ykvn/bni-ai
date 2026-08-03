"""
CAI / CML Application entry point for Qdrant HTTP Server.

Setup in CAI / CML Application:
  Name    : qdrant
  Script  : ask-data/qdrant_server/qdrant_entry.py
"""

import logging
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
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
    """Resolves and ensures the Qdrant persistence folder on disk."""
    default = "/home/cdsw/ask-data/qdrant_server/qdrant_db"
    path = os.getenv("QDRANT_DATA_PATH", default).strip()

    if not os.path.isabs(path):
        path = os.path.abspath(os.path.join("/home/cdsw", path.lstrip("/")))

    Path(path).mkdir(parents=True, exist_ok=True)
    return path


from importlib.metadata import version, PackageNotFoundError

def ensure_qdrant_client() -> None:
    """Ensures qdrant-client is installed in the current environment."""
    try:
        qdrant_ver = version("qdrant-client")
        logging.info("qdrant-client %s already installed", qdrant_ver)
    except PackageNotFoundError:
        logging.info("Installing qdrant-client...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "qdrant-client>=1.7.0"], check=True)

def ensure_qdrant_binary(server_dir: Path) -> Path:
    """
    Ensures the Qdrant server executable binary exists.
    Checks PATH first, then local directory, and automatically downloads the Linux binary if missing.
    """
    binary_in_path = shutil.which("qdrant")
    if binary_in_path:
        logging.info("Found system Qdrant binary at: %s", binary_in_path)
        return Path(binary_in_path)

    local_binary = server_dir / "qdrant"
    if local_binary.exists() and os.access(local_binary, os.X_OK):
        logging.info("Found local Qdrant binary at: %s", local_binary)
        return local_binary

    logging.info("Qdrant binary not found locally. Downloading Qdrant server binary...")
    qdrant_version = os.getenv("QDRANT_VERSION", "v1.13.4")
    url = f"https://github.com/qdrant/qdrant/releases/download/{qdrant_version}/qdrant-x86_64-unknown-linux-musl.tar.gz"

    tar_path = server_dir / "qdrant.tar.gz"
    try:
        logging.info("Downloading Qdrant %s from %s...", qdrant_version, url)
        urllib.request.urlretrieve(url, tar_path)

        logging.info("Extracting Qdrant binary...")
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(path=server_dir)

        tar_path.unlink(missing_ok=True)

        os.chmod(local_binary, 0o755)
        logging.info("✅ Qdrant binary successfully prepared at: %s", local_binary)
        return local_binary
    except Exception as e:
        logging.error("Failed to download Qdrant binary: %s", e)
        raise RuntimeError("Qdrant binary missing and download failed. Please provide a qdrant binary.") from e


def generate_qdrant_config(server_dir: Path, data_path: str, host: str, port: int) -> Path:
    """Generates a dynamic Qdrant configuration YAML file bound to CML runtime parameters."""
    config_path = server_dir / "qdrant_config.yaml"
    grpc_port = port + 1 if port < 65534 else port - 1

    config_content = f"""
storage:
  storage_path: "{data_path}"

service:
  host: "{host}"
  http_port: {port}
  grpc_port: {grpc_port}
  enable_cors: true

telemetry_disabled: true
"""
    config_path.write_text(config_content.strip())
    logging.info("Generated Qdrant config at: %s", config_path)
    return config_path


# 1. Validate environment dependencies
ensure_qdrant_client()

import qdrant_client

server_dir = Path(__file__).resolve().parent if "__file__" in globals() else Path("/home/cdsw/ask-data/qdrant_server")
port = resolve_port()
data_path = resolve_data_path()
host = "127.0.0.1"  # Bound explicitly to loopback for CML Ingress Proxy

qdrant_binary = ensure_qdrant_binary(server_dir)
config_file = generate_qdrant_config(server_dir, data_path, host, port)

from importlib.metadata import version
logging.info("qdrant-client version : %s", version("qdrant-client"))
logging.info("Host                  : %s", host)
logging.info("Port                  : %s", port)
logging.info("Data path             : %s", data_path)
logging.info("Binary path           : %s", qdrant_binary)

# 2. Start Qdrant Server Subprocess
logging.info("=== STARTING QDRANT SERVER ===")

env = {
    **os.environ,
    "QDRANT__SERVICE__HOST": host,
    "QDRANT__SERVICE__HTTP_PORT": str(port),
    "QDRANT__STORAGE__STORAGE_PATH": data_path,
}


def start_proc():
    # Stream stderr directly to sys.stderr to prevent 64KB pipe buffer deadlocks
    cmd = [str(qdrant_binary), "--config-path", str(config_file)]
    return subprocess.Popen(
        cmd,
        stdout=sys.stdout,
        stderr=sys.stderr,
        env=env,
        text=True,
    )


proc = start_proc()
logging.info("Qdrant PID: %s", proc.pid)

time.sleep(5)

if proc.poll() is not None:
    logging.error("Qdrant died immediately with exit code %s!", proc.returncode)
    raise RuntimeError(f"qdrant failed to start (exit code {proc.returncode})")

logging.info("✅ Qdrant is actively listening on %s:%s", host, port)

# Keep-alive process monitoring loop
while True:
    ret = proc.poll()
    if ret is not None:
        logging.error("Qdrant process exited unexpectedly (code %s). Restarting in 5s...", ret)
        time.sleep(5)
        proc = start_proc()
        logging.info("Qdrant restarted, new PID: %s", proc.pid)
    time.sleep(2)