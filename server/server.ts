import { createApp, lakebase, server } from '@databricks/appkit';
import { setupHealthExplorerRoutes } from './routes/lakebase/health-routes';

createApp({
  plugins: [
    lakebase(),
    server(),
  ],
  onPluginsReady(appkit) {
    setupHealthExplorerRoutes(appkit);
  },
}).catch(console.error);
