require('dotenv').config();
const express = require('express');
const CubejsServerCore = require('@cubejs-backend/server-core');

const app = express();

// 1. Capture the CML application port (8100)
const port = process.env.CDSW_APP_PORT || 8100;
delete process.env.PORT;
delete process.env.CUBEJS_PORT;

// 2. Add a basic health check endpoint for CML's internal router
app.get('/health', (req, res) => {
  res.status(200).send('OK');
});

// 3. START EXPRESS IMMEDIATELY ON 127.0.0.1
// This instantly passes CML's strict health check so the UI flips to "Running"
app.listen(port, "127.0.0.1", () => {
  console.log(`✅ Express server securely bound to 127.0.0.1:${port}.`);
  
  // 4. Initialize Cube Core heavily in the background AFTER the port is open
  startCube();
});

const core = CubejsServerCore.create({});

async function startCube() {
  try {
    console.log("⏳ Initializing Cube Core middleware in the background...");
    
    // Attach Cube API routes (/cubejs-api/v1/...) to the running Express app
    await core.initApp(app);
    
    console.log(`✅ Cube Semantic Layer is fully loaded and ready!`);
  } catch (error) {
    console.error('❌ Failed to initialize Cube:', error);
    process.exit(1);
  }
}