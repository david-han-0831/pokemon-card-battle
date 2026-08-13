import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // /api 와 /ws 를 백엔드로 넘긴다.
    // 이렇게 하면 브라우저 입장에서 모든 요청이 같은 오리진이라 CORS 문제가 사라진다.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
})
