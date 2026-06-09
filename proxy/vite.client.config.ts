import { resolve } from 'node:path';
import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    outDir: 'public',
    emptyOutDir: false,
    rollupOptions: {
      input: resolve(__dirname, 'src/ui/client/index.tsx'),
      output: {
        entryFileNames: 'ui-client.js',
        format: 'es',
      },
    },
  },
  esbuild: {
    jsx: 'automatic',
    jsxImportSource: 'hono/jsx/dom',
  },
});
