import os
import sys
import threading
import time
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

from generate_token import get_cdp_token


def start_token_refresher(interval_minutes: int = 45) -> None:
    """
    Background daemon thread that periodically refreshes the CDP_TOKEN 
    directly in the proxy's active OS environment memory space.
    """
    def _refresh_loop():
        while True:
            time.sleep(interval_minutes * 60)
            print("\n🔄 [AUTH ENGINE] Triggering periodic CDP_TOKEN refresh...", flush=True)
            
            new_token = get_cdp_token()
            if new_token:
                # Because LiteLLM is running in THIS exact Python process, updating os.environ 
                # instantly applies to all new incoming requests without needing a restart!
                os.environ["CDP_TOKEN"] = new_token
                print("✅ [AUTH ENGINE] Successfully updated CDP_TOKEN in active runtime context.", flush=True)
            else:
                print("⚠️ [AUTH ENGINE WARNING] Periodic token refresh failed. Retrying next cycle...", flush=True)

    thread = threading.Thread(target=_refresh_loop, daemon=True)
    thread.start()


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


def main() -> None:
    proxy_dir = resolve_proxy_dir()
    os.chdir(proxy_dir)
    config_path = proxy_dir / "litellm_config.yaml"
    print(f"📍 Successfully located configuration file at: {config_path}")
    
    if "QWEN_APP_URL" not in os.environ:
        print("❌ CRITICAL PLATFORM ERROR: 'QWEN_APP_URL' environment variable is missing!")
        sys.exit(1)
        
    print("🔑 [AUTH STARTUP] Requesting initial fresh CDP_TOKEN from Cloudera IAM...")
    initial_token = get_cdp_token()
    if not initial_token:
        print("❌ CRITICAL PLATFORM ERROR: Failed to generate initial CDP_TOKEN!")
        sys.exit(1)
        
    os.environ["CDP_TOKEN"] = initial_token
    print("✅ [AUTH STARTUP] Initial CDP_TOKEN injected into execution environment.")

    app_port = int(os.environ.get("CDSW_APP_PORT", 8100))
    
    # 3. Start background thread to keep token refreshed every 45 minutes
    start_token_refresher(interval_minutes=30)

    print(f"\n📡 Launching In-Process CML LiteLLM Proxy Gateway service on http://127.0.0.1:{app_port}")
    
    # 4. Override sys.argv so LiteLLM's programmatic CLI parses our arguments
    sys.argv = [
        "litellm",
        "--config", str(config_path),
        "--host", "127.0.0.1",
        "--port", str(app_port)
    ]
    
    # 5. Import and run LiteLLM directly in the current process loop
    from litellm.proxy.proxy_cli import main as litellm_main
    
    try:
        litellm_main()
    except KeyboardInterrupt:
        print("\n🛑 Proxy Gateway execution interrupted. Shutting down...")


if __name__ == "__main__":
    main()