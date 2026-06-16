import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8008', changeOrigin: true },
      '/status': { target: 'http://localhost:8008', changeOrigin: true },
      '/health': { target: 'http://localhost:8008', changeOrigin: true },
      '/generate': { target: 'http://localhost:8008', changeOrigin: true },
    },
  },
})
