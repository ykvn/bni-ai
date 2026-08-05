import os
import sys
import threading
import asyncio
from pathlib import Path

# 1. Global config: load the single ask-data/.env BEFORE any service code reads env vars.
_ASK_DATA_ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

import shared.config_loader as config_loader
config_loader.bootstrap(hint=_ASK_DATA_ROOT)

# 2. Add litellm_proxy directory to sys.path
_PROXY_DIR = Path(__file__).resolve().parent if "__file__" in globals() else _ASK_DATA_ROOT / "litellm_proxy"
if str(_PROXY_DIR) not in sys.path:
    sys.path.insert(0, str(_PROXY_DIR))

import litellm
from litellm.integrations.custom_logger import CustomLogger
from generate_token import get_cdp_token


class DynamicCDPAuthHandler(CustomLogger):
    """
    Interceptor hook that overwrites the outgoing Authorization header 
    with a fresh CDP token on EVERY request to Knox Gateway.
    """
    async def async_pre_call_hook(self, *args, **kwargs):
        # Safely extract LiteLLM's internal request dictionary
        req_kwargs = kwargs.get("kwargs", {})
        
        fresh_token = get_cdp_token() or os.getenv("CDP_TOKEN") or os.getenv("CML_TOKEN")
        
        if fresh_token:
            if "extra_headers" not in req_kwargs or req_kwargs["extra_headers"] is None:
                req_kwargs["extra_headers"] = {}
            
            # Mutate the dictionary in-place to inject the fresh token
            req_kwargs["extra_headers"]["Authorization"] = f"Bearer {fresh_token}"
            req_kwargs["extra_headers"]["X-CDSW-API-Key"] = fresh_token


# Register the auth hook globally inside LiteLLM
litellm.callbacks = [DynamicCDPAuthHandler()]


def resolve_proxy_dir() -> Path:
    cwd = Path.cwd()
    candidates = [
        Path(__file__).parent.resolve() if '__file__' in globals() else cwd,
        cwd / "litellm_proxy",
        cwd / "ask-data" / "litellm_proxy",
        Path("/home/cdsw/ask-data/litellm_proxy")
    ]
    for c in candidates:
        if (c / "litellm_config.yaml").exists():
            return c
            
    print(f"❌ CRITICAL SETUP ERROR: Could not locate 'litellm_config.yaml' on disk.")
    sys.exit(1)


def _start_isolated_proxy():
    """Runs LiteLLM inside an isolated thread to bypass Uvicorn's event loop restrictions."""
    # ⚡ Give this thread a clean event loop so Uvicorn doesn't crash
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        from litellm.proxy.proxy_cli import run_server as litellm_proxy_start
    except ImportError:
        from litellm.proxy.proxy_cli import cli as litellm_proxy_start
    
    try:
        litellm_proxy_start()
    except SystemExit:
        pass


def main() -> None:
    proxy_dir = resolve_proxy_dir()
    os.chdir(proxy_dir)
    config_path = proxy_dir / "litellm_config.yaml"
    
    if "QWEN_APP_URL" not in os.environ:
        print("❌ CRITICAL PLATFORM ERROR: 'QWEN_APP_URL' environment variable is missing!")
        sys.exit(1)

    app_port = int(os.environ.get("CDSW_APP_PORT", 8100))
    
    print(f"📡 Launching In-Process LiteLLM Proxy Gateway with Dynamic CDP Auth on http://127.0.0.1:{app_port}")
    
    sys.argv = [
        "litellm",
        "--config", str(config_path),
        "--host", "127.0.0.1",
        "--port", str(app_port)
    ]
    
    # Launch Proxy in a background thread to hide it from CML's active Jupyter loop
    proxy_thread = threading.Thread(target=_start_isolated_proxy, daemon=True)
    proxy_thread.start()
    
    try:
        # Keep the main thread alive so the CML App doesn't exit
        proxy_thread.join()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down Proxy Gateway...")


if __name__ == "__main__":
    main()