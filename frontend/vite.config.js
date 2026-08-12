import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: true,
    port: 5173,
    // `npm run dev` outside Docker talks to the compose stack through nginx.
    proxy: {
      '/api': { target: 'http://localhost:8110', changeOrigin: true },
      '/ws': { target: 'ws://localhost:8110', ws: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        // hls.js (watch page) and recharts (studio) are both large and needed on
        // different routes; splitting them keeps the home feed's bundle small.
        // Rolldown — which backs Vite 8 — requires the function form here; the
        // object form throws at build time.
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('/hls.js/')) return 'player'
          if (id.includes('/recharts/') || id.includes('/d3-') || id.includes('/victory-')) {
            return 'charts'
          }
          if (
            id.includes('/react/') ||
            id.includes('/react-dom/') ||
            id.includes('/react-router/') ||
            id.includes('/react-router-dom/') ||
            id.includes('/scheduler/')
          ) {
            return 'vendor'
          }
          return undefined
        },
      },
    },
  },
})
