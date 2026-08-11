import os
import subprocess
import sys

# Load environment variables from shared config
sys.path.insert(0, "/home/cdsw/ask-data")
from shared import config_loader
config_loader.bootstrap(hint="/home/cdsw/ask-data")

def main():
    print("🚀 Booting Node.js v16 Environment...", flush=True)
    
    # 1. Add locally downloaded Node binaries to system PATH
    current_path = os.environ.get('PATH', '')
    os.environ["PATH"] = f"/home/cdsw/.local/node/bin:{current_path}"
    
    print("🚀 Starting Cube Semantic Layer in Production Mode...", flush=True)
    
    # 2. Navigate to the Cube directory
    cube_dir = "/home/cdsw/ask-data/cube_service"
    os.chdir(cube_dir)
    
    # 3. Map main HTTP API server to CML application port (8100)
    app_port = os.environ.get("CDSW_APP_PORT", "8100")
    os.environ["PORT"] = app_port
    
    # 4. Enforce Production Mode to disable Dev Playground duplicate listeners
    os.environ["NODE_ENV"] = "production"
    os.environ["CUBEJS_DEV_MODE"] = "false"
    
    # 5. Offload internal SQL API to port 15432 so it doesn't collide with port 8100
    os.environ["CUBEJS_SQL_PORT"] = "15432"
    
    # 6. Disable telemetry and external pings
    os.environ["CUBEJS_TELEMETRY"] = "false"
    os.environ["CUBEJS_WEB_SOCKETS"] = "false"
    
    # 7. Start the server using Node and index.js
    print(f"🌐 Starting Cube production API on port {app_port}...", flush=True)
    
    try:
        subprocess.run(["node", "index.js"], check=True)
    except Exception as e:
        print(f"❌ Failed to start Cube: {e}", flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()