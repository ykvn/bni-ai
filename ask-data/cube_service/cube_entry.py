import os
import subprocess
import sys

def main():
    print("🚀 Booting Node.js Environment...", flush=True)
    
    # 1. Add our locally downloaded Node binaries to the system PATH
    current_path = os.environ.get('PATH', '')
    os.environ["PATH"] = f"/home/cdsw/.local/node/bin:{current_path}"
    
    print("🚀 Starting Cube Semantic Layer...", flush=True)
    
    # 2. Navigate to the Cube directory
    cube_dir = "/home/cdsw/ask-data/cube_service"
    os.chdir(cube_dir)
    
    # 3. Map Cube API to CML's exposed application port
    app_port = os.environ.get("CDSW_APP_PORT", "8100")
    os.environ["PORT"] = app_port
    os.environ["CUBEJS_API_PORT"] = app_port
    
    # 4. Disable outbound telemetry and developer tools to prevent internet pings
    os.environ["CUBEJS_TELEMETRY"] = "false"
    os.environ["CUBEJS_DEV_MODE"] = "false"
    os.environ["CUBEJS_WEB_SOCKETS"] = "false"
    
    # 5. Start the server using the local Node binary
    print(f"🌐 Starting Cube server on port {app_port}...", flush=True)
    
    try:
        # Use subprocess to run the npx command, replacing the Python process
        subprocess.run(["npx", "cubejs-server"], check=True)
    except Exception as e:
        print(f"❌ Failed to start Cube: {e}", flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()