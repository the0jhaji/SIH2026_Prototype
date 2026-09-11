import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Bind all interfaces (IPv4 + IPv6 loopback, LAN) to match the backend's
    // 0.0.0.0 — Vite's default 'localhost' may resolve to ::1 only on Windows.
    host: true,
    proxy: {
      // Phase 2+: forward API + WebSocket traffic to the FastAPI backend.
      '/api': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
})