import { createApp } from 'vue'
import App from './App.vue'
import './style.css'
import './workbench.css'
import './command-screen.css'

// FE-71 指挥员口令：本地保存过口令则全局附带；后端 401 时广播事件由 App.vue 弹出输入条。
// 后端未开启口令门（未配置 FIREOPS_COMMANDER_TOKEN）时一切如常。
const rawFetch = window.fetch.bind(window)
window.fetch = async (input, init = {}) => {
  const token = localStorage.getItem('commander-token')
  if (token) {
    init.headers = { ...(init.headers || {}), 'X-Commander-Token': token }
  }
  const response = await rawFetch(input, init)
  if (response.status === 401 && String(response.url).includes('/api/')) {
    window.dispatchEvent(new CustomEvent('commander-auth-required'))
  }
  return response
}

createApp(App).mount('#app')
