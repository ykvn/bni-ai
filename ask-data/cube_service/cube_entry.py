import os
import subprocess
import sys
import shutil

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
    
    # 3. Automatically copy missing Hive IDL files if they don't exist
    jshs2_idl_path = "/home/cdsw/ask-data/cube_service/node_modules/jshs2/idl"
    target_idl_path = "/home/cdsw/ask-data/cube_service/idl"
    
    if os.path.exists(jshs2_idl_path) and not os.path.exists(target_idl_path):
        print("📁 Auto-copying Hive IDL files to project root...", flush=True)
        shutil.copytree(jshs2_idl_path, target_idl_path)
    
    # 4. Setup Port and Env Flags
    app_port = os.environ.get("CDSW_APP_PORT", "8100")
    os.environ["PORT"] = app_port
    
    os.environ["NODE_ENV"] = "production"
    os.environ["CUBEJS_DEV_MODE"] = "false"
    os.environ["CUBEJS_TELEMETRY"] = "false"
    os.environ["CUBEJS_WEB_SOCKETS"] = "false"
    os.environ["CUBEJS_API_SECRET"] = "Cloudera1!"
    os.environ["CUBEJS_CACHE_AND_QUEUE_DRIVER"] = "memory"
    
    print(f"🌐 Starting Node.js on port {app_port}...", flush=True)
    
    # 5. Use subprocess so Python stays alive and CML can track the application
    try:
        subprocess.run(["node", "index.js"], check=True)
    except Exception as e:
        print(f"❌ Failed to start Cube: {e}", flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()