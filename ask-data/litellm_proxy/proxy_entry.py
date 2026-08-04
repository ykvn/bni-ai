import os
import sys
import subprocess
import threading
import time
from pathlib import Path

# 1. Global config: load the single ask-data/.env BEFORE any service code reads env vars.
_ASK_DATA_ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

import shared.config_loader as config_loader
config_loader.bootstrap(hint=_ASK_DATA_ROOT)

# 2. Add litellm_proxy directory to sys.path BEFORE importing generate_token
_PROXY_DIR = Path(__file__).resolve().parent if "__file__" in globals() else _ASK_DATA_ROOT / "litellm_proxy"
if str(_PROXY_DIR) not in sys.path:
    sys.path.insert(0, str(_PROXY_DIR))

from generate_token import get_cdp_token


def start_token_refresher(env_dict: dict, interval_minutes: int = 45) -> None:
    """
    Background daemon thread that periodically refreshes the CDP_TOKEN 
    in both os.environ and the subprocess env dictionary before JWT expiration.
    """
    def _refresh_loop():
        while True:
            time.sleep(interval_minutes * 60)
            print("🔄 [AUTH ENGINE] Triggering periodic CDP_TOKEN refresh...", flush=True)
            new_token = get_cdp_token()
            if new_token:
                os.environ["CDP_TOKEN"] = new_token
                env_dict["CDP_TOKEN"] = new_token
                print("✅ [AUTH ENGINE] Successfully updated CDP_TOKEN in runtime context.", flush=True)
            else:
                print("⚠️ [AUTH ENGINE WARNING] Periodic token refresh failed. Retrying next cycle...", flush=True)

    thread = threading.Thread(target=_refresh_loop, daemon=True)
    thread.start()


def ensure_dependencies(proxy_dir: Path, env: dict) -> None:
    """
    Validates and installs packages from requirements.txt directly 
    into the CML application container runtime environment.
    """
    req_file = proxy_dir / "requirements.txt"
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


def resolve_proxy_dir() -> Path:
    """Robustly finds the litellm_proxy directory regardless of where CML launches the script."""
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
    print(f"Searched target locations: {[str(c) for c in candidates]}")
    sys.exit(1)


def main() -> None:
    # 1. Use the robust resolver to lock in the correct directory
    proxy_dir = resolve_proxy_dir()
    os.chdir(proxy_dir)
    
    config_path = proxy_dir / "litellm_config.yaml"
    print(f"📍 Successfully located configuration file at: {config_path}")
    
    # 2. ENTERPRISE BOUNDARY GUARD: Assert variable configuration before execution
    if "QWEN_APP_URL" not in os.environ:
        print("❌ CRITICAL PLATFORM ERROR: 'QWEN_APP_URL' environment variable is missing!")
        print("Please configure this variable in the CML Project Application Dashboard settings.")
        sys.exit(1)
        
    print(f"🔗 Target routing context successfully bound to: {os.environ['QWEN_APP_URL']}")

    # 3. GENERATE INITIAL CDP TOKEN BEFORE SERVICE LAUNCH
    print("🔑 [AUTH STARTUP] Requesting initial fresh CDP_TOKEN from Cloudera IAM...")
    initial_token = get_cdp_token()
    if not initial_token:
        print("❌ CRITICAL PLATFORM ERROR: Failed to generate initial CDP_TOKEN!")
        sys.exit(1)
        
    os.environ["CDP_TOKEN"] = initial_token
    print("✅ [AUTH STARTUP] Initial CDP_TOKEN injected into execution environment.")

    # 4. Enforce the dynamically allocated port by the CML environment
    app_port = int(os.environ.get("CDSW_APP_PORT", 8100))
    
    # 5. Inject PYTHONPATH and runtime variables for isolated subprocess execution
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{proxy_dir}:{pythonpath}" if pythonpath else str(proxy_dir)
    env["CDP_TOKEN"] = initial_token

    # 6. Run standard dependency validation routine
    ensure_dependencies(proxy_dir, env)
    
    # 7. Start background thread to keep token refreshed every 45 minutes
    start_token_refresher(env_dict=env, interval_minutes=45)

    # 8. Standardized command execution pattern
    cmd = [
        "litellm",
        "--config", str(config_path),
        "--host", "127.0.0.1",
        "--port", str(app_port)
    ]
    
    print(f"\n📡 Launching Standalone CML LiteLLM Proxy Gateway service...")
    print(f"🌐 Network Bound: http://127.0.0.1:{app_port}")
    
    # Launch LiteLLM safely in its own isolated process
    process = subprocess.Popen(cmd, cwd=str(proxy_dir), env=env)
    
    try:
        process.wait()
    except KeyboardInterrupt:
        print("\n🛑 Gateway execution interrupted. Shutting down Proxy...")
        process.terminate()


if __name__ == "__main__":
    main()