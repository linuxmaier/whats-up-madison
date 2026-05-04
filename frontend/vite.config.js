import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

import { cloudflare } from "@cloudflare/vite-plugin";

const backendUrl = process.env.VITE_BACKEND_URL || 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), cloudflare()],
  server: {
    proxy: {
      '/events': backendUrl,
      '/admin': backendUrl,
      '/feedback': backendUrl,
    },
  },
})