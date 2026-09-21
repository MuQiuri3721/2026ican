import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import http from 'node:http'

// 长跑后代理楔死根治（E2E round2-5 批量挂实测）：http-proxy 默认复用 keep-alive
// socket，后端重启/空闲超时后死连接被复用 → POST 挂起无响应。禁用 keep-alive，
// 每请求新建连接（本机回环开销可忽略）。
const apiProxy = (port) => ({
  target: `http://127.0.0.1:${port}`,
  changeOrigin: true,
  agent: new http.Agent({ keepAlive: false }),
})

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': apiProxy(8000),
    },
  },
  // vite preview 默认不继承 server.proxy——生产模式演示（build + preview）必须显式配置
  preview: {
    port: 4173,
    proxy: {
      '/api': apiProxy(8000),
    },
  },
})
