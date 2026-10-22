import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 开发期：npm run dev（Vite 5173 端口，/api 代理到 FastAPI 8000）
// 生产期：npm run build 产出 dist/，由 FastAPI 直接托管
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  build: { outDir: 'dist' },
})
