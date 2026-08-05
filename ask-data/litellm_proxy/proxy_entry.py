import os
import sys
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

import litellm
from litellm.integrations.custom_logger import CustomLogger
from generate_token import get_cdp_token


class CDPTokenManager:
    """
    Self-healing Token Manager that caches the CDP_TOKEN in memory
    and automatically fetches a fresh one from Cloudera IAM when it reaches 40 minutes old.
    """
    _token = None
    _fetched_at = 0
    _TTL_SECONDS = 40 * 60  # 40 minutes (tokens expire at 60 mins)

    @classmethod
    def get_valid_token(cls) -> str:
        now = time.time()
        if cls._token is None or (now - cls._fetched_at) > cls._TTL_SECONDS:
            print("🔄 [AUTH GATEWAY] Generating fresh CDP Workload Token from Cloudera IAM...", flush=True)
            new_tok = get_cdp_token()
            if new_tok:
                cls._token = new_tok
                cls._fetched_at = now
                os.environ["CDP_TOKEN"] = new_tok
                print("✅ [AUTH GATEWAY] CDP Workload Token refreshed and cached successfully.", flush=True)
            else:
                print("⚠️ [AUTH GATEWAY WARNING] Token generation failed. Falling back to environment variable.", flush=True)
                cls._token = os.getenv("CDP_TOKEN") or os.getenv("CML_TOKEN", "")
        return cls._token


class DynamicKnoxAuthHook(CustomLogger):
    """
    LiteLLM Interceptor Callback that injects the active CDP_TOKEN into 
    the Authorization header sent to Knox Gateway on EVERY request.
    """
    def _inject_auth(self, kwargs):
        token = CDPTokenManager.get_valid_token()
        if token:
            if "extra_headers" not in kwargs or kwargs["extra_headers"] is None:
                kwargs["extra_headers"] = {}
            kwargs["extra_headers"]["Authorization"] = f"Bearer {token}"
            kwargs["extra_headers"]["X-CDSW-API-Key"] = token

    def log_pre_api_call(self, model, messages, kwargs):
        self._inject_auth(kwargs)
        return kwargs

    async def async_pre_call_hook(self, user_api_key, alias, model, messages, kwargs, model_response):
        self._inject_auth(kwargs)
        return kwargs


# Register the auth interceptor callback inside LiteLLM
litellm.callbacks = [DynamicKnoxAuthHook()]


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
    print(f"📍 Located configuration file at: {config_path}")
    
    if "QWEN_APP_URL" not in os.environ:
        print("❌ CRITICAL PLATFORM ERROR: 'QWEN_APP_URL' environment variable is missing!")
        sys.exit(1)

    # Pre-warm initial token in cache
    CDPTokenManager.get_valid_token()

    app_port = int(os.environ.get("CDSW_APP_PORT", 8100))
    print(f"📡 Launching LiteLLM Gateway Service with Dynamic Auth Interceptor on http://127.0.0.1:{app_port}")
    
    sys.argv = [
        "litellm",
        "--config", str(config_path),
        "--host", "127.0.0.1",
        "--port", str(app_port)
    ]
    
    from litellm.proxy.proxy_cli import main as litellm_main
    
    try:
        litellm_main()
    except KeyboardInterrupt:
        print("\n🛑 Gateway execution interrupted. Shutting down...")


if __name__ == "__main__":
    main()