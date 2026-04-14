import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 6328,  // HeNe 激光波长 632.8 nm
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
