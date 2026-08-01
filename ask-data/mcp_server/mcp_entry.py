import os
import sys
import subprocess
from pathlib import Path

# 🎯 Global config: load the single ask-data/.env BEFORE any service code reads env vars.
# Robust to script execution (__file__ defined) AND notebook/REPL execution (no __file__).
_ASK_DATA_ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path.cwd()
while not (_ASK_DATA_ROOT / "shared" / "config_loader.py").exists() and _ASK_DATA_ROOT.parent != _ASK_DATA_ROOT:
    _ASK_DATA_ROOT = _ASK_DATA_ROOT.parent
if not (_ASK_DATA_ROOT / "shared" / "config_loader.py").exists():
    _ASK_DATA_ROOT = (
        Path("/home/cdsw/ask-data")
        if Path("/home/cdsw/ask-data/shared/config_loader.py").exists()
        else _ASK_DATA_ROOT
    )
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

import shared.config_loader as config_loader
config_loader.load_project_env()

def ensure_dependencies(mcp_dir: Path, env: dict) -> None:
    """
    Validates and installs packages from requirements.txt directly 
    into the CML application container runtime environment.
    """
    req_file = mcp_dir / "requirements.txt"
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

def resolve_mcp_dir() -> Path:
    """Robustly finds the mcp_server directory regardless of where CML launches the script."""
    cwd = Path.cwd()
    
    candidates = [
        Path(__file__).parent.resolve() if '__file__' in globals() else cwd,
        cwd / "mcp_server",
        cwd / "ask-data" / "mcp_server",
        Path("/home/cdsw/ask-data/mcp_server")
    ]
    
    for c in candidates:
        if (c / "app" / "main.py").exists():
            return c
            
    print(f"❌ Critical Error: Could not locate 'app/main.py'. Are you sure the folder structure is correct?")
    return cwd

def main() -> None:
    # 1. Lock in the correct directory execution context
    mcp_dir = resolve_mcp_dir()
    os.chdir(mcp_dir)
    
    # 2. Extract the dynamically allocated port by the CML environment
    app_port = int(os.environ.get("CDSW_APP_PORT"))
    
    # 3. Patch environment variables with absolute PYTHONPATH injections
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{mcp_dir}:{pythonpath}" if pythonpath else str(mcp_dir)
    
    # 4. Handle dependency resolution before thread initialization
    ensure_dependencies(mcp_dir, env)
    
    # 5. Standardized operational startup parameter array targeting app.main:app
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
    
    print(f"🌐 Starting Aligned Production MCP Server via subprocess on http://127.0.0.1:{app_port}")
    print(f"📍 Resolved Execution Root Context: {mcp_dir}")
    
    # Launch Uvicorn cleanly inside its own isolated operating system process
    process = subprocess.Popen(cmd, cwd=str(mcp_dir), env=env)
    
    try:
        process.wait()
    except KeyboardInterrupt:
        print("\n🛑 Gateway loop execution interrupted. Purging active proxy sockets...")
        process.terminate()

if __name__ == "__main__":
    main()