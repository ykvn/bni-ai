import os
import subprocess
import sys

# Load environment variables
sys.path.insert(0, "/home/cdsw/ask-data")
from shared import config_loader
config_loader.bootstrap(hint="/home/cdsw/ask-data")

def main():
    print("🚀 Booting Node.js Environment from Python...", flush=True)
    
    # 1. Update PATH for Node
    current_path = os.environ.get('PATH', '')
    os.environ["PATH"] = f"/home/cdsw/.local/node/bin:{current_path}"
    
    # 2. Navigate to Cube directory
    os.chdir("/home/cdsw/ask-data/cube_service")
    
    # 3. Setup Port and Env Flags
    app_port = os.environ.get("CDSW_APP_PORT", "8100")
    os.environ["PORT"] = app_port
    
    os.environ["NODE_ENV"] = "production"
    os.environ["CUBEJS_DEV_MODE"] = "false"
    os.environ["CUBEJS_TELEMETRY"] = "false"
    os.environ["CUBEJS_WEB_SOCKETS"] = "false"
    os.environ["CUBEJS_API_SECRET"] = "Cloudera1!"
    
    print(f"🌐 Starting Node.js on port {app_port}...", flush=True)
    
    # 4. Use subprocess so Python stays alive and CML can track the application
    try:
        subprocess.run(["node", "index.js"], check=True)
    except Exception as e:
        print(f"❌ Failed to start Cube: {e}", flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()