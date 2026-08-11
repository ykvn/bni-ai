require('dotenv').config();
const CubejsServer = require('@cubejs-backend/server');

const server = new CubejsServer();

server.listen().then(({ port }) => {
  console.log(`✅ Cube Legacy Semantic Layer successfully listening on port ${port}`);
}).catch(e => {
  console.error('❌ Fatal error:', e);
  process.exit(1);
});