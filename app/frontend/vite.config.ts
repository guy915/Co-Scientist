import {defineConfig} from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'path';
import {readFileSync} from 'node:fs';

// Preview must exercise the same policy as Cloudflare, including on deep links.
const previewHeaders = Object.fromEntries(
  readFileSync(path.resolve(__dirname, 'public/_headers'), 'utf8')
    .split('\n/*\n')[1]
    .trim()
    .split('\n')
    .map(line => {
      const separator = line.indexOf(':');
      return [
        line.slice(0, separator).trim(),
        line.slice(separator + 1).trim(),
      ];
    }),
);
const previewApi = process.env.VITE_API_BASE_URL;
if (previewApi && /^http:\/\/127\.0\.0\.1:\d+$/.test(previewApi)) {
  previewHeaders['Content-Security-Policy'] = previewHeaders[
    'Content-Security-Policy'
  ].replace('connect-src', `connect-src ${previewApi}`);
}

export default defineConfig({
  preview: {headers: previewHeaders},
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: process.env.COSCI_FRONTEND_DIST || 'dist',
    rollupOptions: {
      output: {
        // React changes far less often than app code; a separate chunk keeps
        // its immutable cache entry across deploys.
        manualChunks(id) {
          if (
            /[\\/]node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom)[\\/]/.test(
              id,
            )
          ) {
            return 'react';
          }
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test_setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    server: {
      // material-color-utilities ships extensionless ESM imports that Vitest's
      // default externalizer cannot resolve; inline it so it is bundled.
      deps: {inline: ['@material/material-color-utilities']},
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {target: 'http://localhost:8008', changeOrigin: true},
      '/status': {target: 'http://localhost:8008', changeOrigin: true},
      '/health': {target: 'http://localhost:8008', changeOrigin: true},
    },
  },
});
