import os
import sys
import uvicorn
from pathlib import Path

# 1. Resolve Root Directory
_ASK_DATA_ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path("/home/cdsw/ask-data")
if str(_ASK_DATA_ROOT) not in sys.path:
    sys.path.insert(0, str(_ASK_DATA_ROOT))

import shared.config_loader as config_loader
config_loader.bootstrap(hint=_ASK_DATA_ROOT)

# 2. Resolve Service Directory
CREWAI_DIR = _ASK_DATA_ROOT / "crewai_service"
if str(CREWAI_DIR) not in sys.path:
    sys.path.insert(0, str(CREWAI_DIR))

def main():
    app_port = int(os.environ.get("CDSW_APP_PORT", 8091))
    print(f"🌐 [CrewAI Service App] Starting Engine on http://127.0.0.1:{app_port}")
    
    uvicorn.run(
        "crewai_service.app.main:app",
        host="127.0.0.1",
        port=app_port,
        log_level="warning"
    )

if __name__ == "__main__":
    main()