import { defineConfig } from 'vite';
import { cpSync } from 'node:fs';
import { join } from 'node:path';
export default defineConfig({
  base: '/visualization/',
  define: { CESIUM_BASE_URL: JSON.stringify('/visualization/cesium/') },
  plugins: [{name: 'copy-cesium-offline', closeBundle() {
    for (const name of ['Assets', 'ThirdParty', 'Widgets', 'Workers'])
      cpSync(join('node_modules/cesium/Build/Cesium', name), join('dist/cesium', name), {recursive: true});
  }}],
  build: {outDir:'dist', emptyOutDir:true}
});
