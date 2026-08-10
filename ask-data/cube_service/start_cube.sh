#!/bin/bash

echo "🚀 Booting Node.js Environment..."

# 1. Add our locally downloaded Node binaries to the system PATH
export PATH=/home/cdsw/.local/node/bin:$PATH

echo "🚀 Starting Cube Semantic Layer..."

# 2. Navigate to the Cube directory
cd /home/cdsw/ask-data/cube-service

# 3. Map Cube API to CML's exposed application port
export PORT=$CDSW_APP_PORT
export CUBEJS_API_PORT=$CDSW_APP_PORT

# 4. Disable outbound telemetry and developer tools to prevent internet pings
export CUBEJS_TELEMETRY=false
export CUBEJS_DEV_MODE=false
export CUBEJS_WEB_SOCKETS=false

# 5. Start the server using the local Node binary
echo "🌐 Starting Cube server on port $CDSW_APP_PORT..."
npx cubejs-server