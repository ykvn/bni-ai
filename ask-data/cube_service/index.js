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

// 4. Attach Cube API routes (/cubejs-api/v1/...) to the Express app
core.initApp(app);

// 5. Express binds to port 8100 exactly once
app.listen(port, () => {
  console.log(`✅ Cube Semantic Layer Express API successfully listening on port ${port}`);
});