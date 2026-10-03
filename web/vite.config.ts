import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Разработка: `python -m atlas --server` (порт 8765) и `npm run dev` — запросы /api проксируются в ядро.
// Сборка кладётся в atlas/web/dist; её раздаёт само ядро, Node пользователю не нужен.
export default defineConfig({
  plugins: [react()],
  base: '/',
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8765' } },
  build: { outDir: '../atlas/web/dist', emptyOutDir: true, chunkSizeWarningLimit: 1500 },
})
