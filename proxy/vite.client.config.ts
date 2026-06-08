import { resolve } from 'node:path';
import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    outDir: 'public',
    emptyOutDir: false,
    rollupOptions: {
      input: resolve(__dirname, 'src/dashboard/client/index.tsx'),
      output: {
        entryFileNames: 'dashboard-client.js',
        format: 'es',
      },
    },
  },
  esbuild: {
    jsx: 'automatic',
    jsxImportSource: 'hono/jsx/dom',
  },
});
