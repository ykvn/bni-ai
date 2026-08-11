require('dotenv').config();
const express = require('express');
const CubejsServerCore = require('@cubejs-backend/server-core');

const app = express();

// Initialize Cube Core strictly as an HTTP API
const core = CubejsServerCore.create({
  devMode: false,
  telemetry: false,
});

// Attach Cube API routes (/cubejs-api/v1/...) to Express
core.initApp(app);

const port = process.env.PORT || 8100;

// Bind to HTTP port exactly once
app.listen(port, () => {
  console.log(`✅ Cube Semantic Layer HTTP API successfully listening on port ${port}`);
});