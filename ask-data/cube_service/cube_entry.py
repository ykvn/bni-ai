import os
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
    
    print(f"🌐 Transforming Python process into Node.js on port {app_port}...", flush=True)
    
    # 4. Flush standard output before process replacement
    sys.stdout.flush()
    sys.stderr.flush()
    
    # 5. PROCESS REPLACEMENT: 
    # Python completely drops its PID and resources, instantly handing them to Node.
    # This guarantees Python cannot block port 8100.
    os.execvpe("node", ["node", "index.js"], os.environ)

if __name__ == "__main__":
    main()