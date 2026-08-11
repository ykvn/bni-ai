require('dotenv').config();
const express = require('express');
const CubejsServerCore = require('@cubejs-backend/server-core');

const app = express();

// 1. Capture the CML application port for Express
const port = process.env.PORT || process.env.CDSW_APP_PORT || 8100;

// 2. Unset process.env.PORT so CubejsServerCore does not create a duplicate standalone listener
delete process.env.PORT;
delete process.env.CUBEJS_PORT;

// 3. Initialize Cube Core strictly as a middleware generator
const core = CubejsServerCore.create({});

// 4. Force JavaScript to wait for Cube to initialize before starting the server
async function startServer() {
  try {
    console.log("⏳ Initializing Cube Core middleware...");
    await core.initApp(app);
    
    // 5. Express binds to the port ONLY after Cube is ready
    app.listen(port, () => {
      console.log(`✅ Cube Semantic Layer Express API successfully listening on port ${port}`);
    });
  } catch (error) {
    console.error('❌ Failed to initialize Cube:', error);
    process.exit(1);
  }
}

startServer();