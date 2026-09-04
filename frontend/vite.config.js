import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        // Vite 8 / rolldown requires manualChunks as a function
        manualChunks(id) {
          if (
            id.includes('/node_modules/react/') ||
            id.includes('/node_modules/react-dom/') ||
            id.includes('/node_modules/react-router')
          ) {
            return 'vendor-react'
          }
          if (id.includes('@tanstack')) {
            return 'vendor-query'
          }
          if (id.includes('lucide-react')) {
            return 'vendor-lucide'
          }
          if (
            id.includes('/node_modules/axios/') ||
            id.includes('/node_modules/recharts/')
          ) {
            return 'vendor-misc'
          }
        },
      },
    },
  },
})
