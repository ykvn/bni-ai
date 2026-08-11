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
    
    # 2. Terminate lingering Node processes to guarantee port 8100 is free
    try:
        subprocess.run(["pkill", "-9", "-f", "node"], stderr=subprocess.DEVNULL)
    except Exception:
        pass
        
    print("🚀 Starting Cube Semantic Layer in Production Mode...", flush=True)
    
    # 3. Navigate to the Cube directory
    cube_dir = "/home/cdsw/ask-data/cube_service"
    os.chdir(cube_dir)
    
    # 4. Map main HTTP API server to CML application port (8100)
    app_port = os.environ.get("CDSW_APP_PORT", "8100")
    os.environ["PORT"] = app_port
    
    # 5. Enforce Production Mode (disables dev playground & duplicate listeners)
    os.environ["NODE_ENV"] = "production"
    os.environ["CUBEJS_DEV_MODE"] = "false"
    
    # 6. Ensure SQL API is UNSET so Cube skips @cubejs-backend/native
    if "CUBEJS_SQL_PORT" in os.environ:
        del os.environ["CUBEJS_SQL_PORT"]
    
    # 7. Disable telemetry and external pings
    os.environ["CUBEJS_TELEMETRY"] = "false"
    os.environ["CUBEJS_WEB_SOCKETS"] = "false"
    
    # 8. Start the pure-JS server using Node and index.js
    print(f"🌐 Starting Cube production API on port {app_port}...", flush=True)
    
    try:
        subprocess.run(["node", "index.js"], check=True)
    except Exception as e:
        print(f"❌ Failed to start Cube: {e}", flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()