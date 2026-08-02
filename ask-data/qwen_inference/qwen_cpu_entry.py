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


def ensure_dependencies(target_dir: Path, env: dict) -> None:
    """
    Validates and installs packages from requirements.txt directly 
    into the CML application container runtime environment.
    """
    req_file = target_dir / "requirements.txt"
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

def resolve_qwen_dir() -> Path:
    """Robustly finds the qwen_inference directory regardless of where CML launches the script."""
    cwd = Path.cwd()
    
    # Generate a list of probable locations for the app folder
    candidates = [
        Path(__file__).parent.resolve() if '__file__' in globals() else cwd,
        cwd / "qwen_inference",
        cwd / "ask-data" / "qwen_inference",
    ]
    
    # Return the first path that actually contains app/main.py
    for c in candidates:
        if (c / "app" / "main.py").exists():
            return c
            
    print(f"❌ Critical Error: Could not locate 'app/main.py'. Are you sure the 'app' folder exists?")
    return cwd

def main() -> None:
    # 1. Use the robust resolver to lock in the correct directory
    qwen_dir = resolve_qwen_dir()
    os.chdir(qwen_dir)
    
    # 2. Enforce the dynamically allocated port
    app_port = int(os.environ.get("CDSW_APP_PORT"))
    
    # 3. Inject PYTHONPATH
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{qwen_dir}:{pythonpath}" if pythonpath else str(qwen_dir)
    
    # 4. Run standard dependency validation routine
    ensure_dependencies(qwen_dir, env)
    
    # 5. Standardized Uvicorn call pointing directly to app/main.py
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
    
    print(f"🌐 Starting Aligned CPU Inference Server via subprocess on http://127.0.0.1:{app_port}")
    print(f"📍 Resolved Working Directory: {qwen_dir}")
    
    # Launch Uvicorn safely in its own process
    process = subprocess.Popen(cmd, cwd=str(qwen_dir), env=env)
    
    try:
        process.wait()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down Inference Server...")
        process.terminate()

if __name__ == "__main__":
    main()