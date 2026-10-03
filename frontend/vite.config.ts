import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backend = 'http://localhost:3000'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    vue(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  // Dev only: the app calls the backend with relative paths, so forward them to Flask.
  server: {
    proxy: {
      '/api': backend,
      // POST / is the combine endpoint; GET / must still serve the app.
      '^/$': {
        target: backend,
        bypass: (req) => (req.method === 'POST' ? undefined : req.url),
      },
    },
  },
})
