import path from 'node:path';
import { fileURLToPath } from 'node:url';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const rootDir = path.dirname(fileURLToPath(import.meta.url));
const apiTarget = `http://localhost:${process.env.PORT ?? '8080'}`;

export default defineConfig({
  root: path.join(rootDir, 'src/ui/client'),
  base: '/assets/',
  plugins: [
    react({
      jsxRuntime: 'automatic',
      jsxImportSource: 'react',
    }),
    tailwindcss(),
  ],
  esbuild: {
    jsx: 'automatic',
    jsxImportSource: 'react',
  },
  optimizeDeps: {
    esbuildOptions: {
      jsx: 'automatic',
      jsxImportSource: 'react',
    },
  },
  server: {
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
      '/ui/backend-config': { target: apiTarget, changeOrigin: true },
      '/ui/cost-rates': { target: apiTarget, changeOrigin: true },
      '/ui/investment-data': { target: apiTarget, changeOrigin: true },
      '/v1': { target: apiTarget, changeOrigin: true },
      '/favicon.ico': { target: apiTarget, changeOrigin: true },
    },
  },
  resolve: {
    alias: {
      '@shared': path.join(rootDir, 'src/shared'),
    },
  },
  build: {
    outDir: path.join(rootDir, 'public/assets'),
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: 'ui.js',
        assetFileNames: 'ui.[ext]',
      },
    },
  },
});
