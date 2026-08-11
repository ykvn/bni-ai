require('dotenv').config();
const express = require('express');
const CubejsServerCore = require('@cubejs-backend/server-core');

const app = express();

// 1. Target CML's exposed application port (8100)
const port = process.env.CDSW_APP_PORT || process.env.PORT || 8100;

// 2. Unset PORT variables so Cube Core doesn't try to bind a duplicate listener
delete process.env.PORT;
delete process.env.CUBEJS_PORT;

// 3. Initialize Cube Core
const core = CubejsServerCore.create({});

// 4. Initialize and attach to Express
async function startServer() {
  try {
    console.log("⏳ Initializing Cube Core middleware...");
    await core.initApp(app);
    
    // 5. Express binds strictly to port 8100
    app.listen(port, () => {
      console.log(`✅ Cube Semantic Layer Express API successfully listening on port ${port}`);
    });
  } catch (error) {
    console.error('❌ Failed to initialize Cube:', error);
    process.exit(1);
  }
}

startServer();