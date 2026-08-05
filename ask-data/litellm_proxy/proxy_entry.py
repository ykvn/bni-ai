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
        # LiteLLM's real signature is (user_api_key_dict, cache, data, call_type).
        # We absorb *args/**kwargs to survive version differences across
        # LiteLLM releases, but we must actually locate the real `data`
        # dict rather than reading/writing a disconnected copy — otherwise
        # the token injection silently does nothing.
        data = kwargs.get("data")
        if data is None and len(args) >= 3:
            data = args[2]  # positional slot 3 (after self) = data

        if not isinstance(data, dict):
            # Couldn't find the real request dict this call — do nothing
            # rather than risk corrupting/replacing it with something empty.
            print("⚠️ [DynamicCDPAuthHandler] Could not locate request 'data' dict; skipping auth injection this call.")
            return None

        fresh_token = get_cdp_token() or os.getenv("CDP_TOKEN") or os.getenv("CML_TOKEN")

        if fresh_token:
            extra_headers = data.get("extra_headers") or {}
            # Mutate the dictionary in-place to inject the fresh token
            extra_headers["Authorization"] = f"Bearer {fresh_token}"
            extra_headers["X-CDSW-API-Key"] = fresh_token
            data["extra_headers"] = extra_headers
        else:
            print("⚠️ [DynamicCDPAuthHandler] No CDP token available; request sent without refreshed auth headers.")

        # Returning the same (now-enriched) data dict is safe — it still
        # has 'model', 'messages', etc. intact, unlike returning a fresh
        # or empty dict which would silently strip them downstream.
        return data


# Register the auth hook globally inside LiteLLM
litellm.callbacks = [DynamicCDPAuthHandler()]


def resolve_proxy_dir() -> Path:
    cwd = Path.cwd()
    candidates = [
        Path(__file__).parent.resolve() if '__file__' in globals() else cwd,
        cwd / "litellm_proxy",
        cwd / "ask-data" / "litellm_proxy",
        Path("/home/cdsw/ask-data/litellm_proxy"),
    ]
    for c in candidates:
        if (c / "litellm_config.yaml").exists():
            return c

    print("❌ CRITICAL SETUP ERROR: Could not locate 'litellm_config.yaml' on disk.")
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

    if "AI_INFERENCE_URL" not in os.environ:
        print("❌ CRITICAL PLATFORM ERROR: 'AI_INFERENCE_URL' environment variable is missing!")
        sys.exit(1)

    app_port = int(os.environ.get("CDSW_APP_PORT", 8100))

    print(f"📡 Launching In-Process LiteLLM Proxy Gateway with Dynamic CDP Auth on http://127.0.0.1:{app_port}")

    sys.argv = [
        "litellm",
        "--config", str(config_path),
        "--host", "127.0.0.1",
        "--port", str(app_port),
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