import { createApp, lakebase, server } from '@databricks/appkit';
import { setupCareGapRoutes } from './routes/caregap-routes';
import { setupHealthExplorerRoutes } from './routes/lakebase/health-routes';

createApp({
  plugins: [
    lakebase(),
    server(),
  ],
  onPluginsReady(appkit) {
    setupCareGapRoutes(appkit);
    setupHealthExplorerRoutes(appkit);
  },
}).catch(console.error);
