import os
import subprocess
import sys

# Load environment variables
sys.path.insert(0, "/home/cdsw/ask-data")
from shared import config_loader
config_loader.bootstrap(hint="/home/cdsw/ask-data")

def main():
    print("🚀 Booting Node.js v16 Environment...", flush=True)
    
    # 1. Add locally downloaded Node binaries to system PATH
    current_path = os.environ.get('PATH', '')
    os.environ["PATH"] = f"/home/cdsw/.local/node/bin:{current_path}"
    
    # 2. Aggressively clear port 8100 (Kills anything holding it, not just Node)
    try:
        subprocess.run(["fuser", "-k", "8100/tcp"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    except Exception:
        pass
        
    print("🚀 Starting Cube Semantic Layer (Express HTTP API)...", flush=True)
    
    # 3. Navigate to the Cube directory
    cube_dir = "/home/cdsw/ask-data/cube_service"
    os.chdir(cube_dir)
    
    # 4. Map HTTP API server to CML application port (Use 8101 for local testing!)
    app_port = os.environ.get("CDSW_APP_PORT", "8101")
    
    # Force it to 8101 if we are inside a Jupyter session to avoid colliding with the IDE
    if "JPY_PARENT_PID" in os.environ or "DATAPANEL_SESSION_ID" in os.environ:
        app_port = "8101"
        
    os.environ["PORT"] = app_port
    
    # 5. Production env flags
    os.environ["NODE_ENV"] = "production"
    os.environ["CUBEJS_DEV_MODE"] = "false"
    os.environ["CUBEJS_TELEMETRY"] = "false"
    os.environ["CUBEJS_WEB_SOCKETS"] = "false"
    
    # 6. Start Express server
    print(f"🌐 Starting Cube API on port {app_port}...", flush=True)
    
    try:
        subprocess.run(["node", "index.js"], check=True)
    except Exception as e:
        print(f"❌ Failed to start Cube: {e}", flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()