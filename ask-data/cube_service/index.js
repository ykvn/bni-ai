require('dotenv').config();
const CubejsServer = require('@cubejs-backend/server-core');

// Initialize the Cube Core Server
const server = CubejsServer.create();

// Boot it up on the port specified by the environment
server.start()
  .then(({ port }) => {
    console.log(`✅ Cube Semantic Layer successfully listening on port ${port}`);
  })
  .catch((e) => {
    console.error('❌ Fatal error during Cube start:', e);
    process.exit(1);
  });