import { computed, ref } from 'vue'
import { logText, logTime } from '../utils/labels'

export function useLogs(initial = []) {
  const logs = ref(initial)

  function addLog(message, details = {}) {
    // 本地时间（与后端事件 datetime.now() 同区）：曾用 toISOString（UTC）导致
    // 任务日志页前端/后端时间混排相差 8 小时（第 8 轮视觉走查发现）
    const now = new Date()
    const pad = (n) => String(n).padStart(2, '0')
    const timestamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`
    logs.value.unshift({ timestamp, stage: 'ui', source: 'frontend', message, ...details })
    if (logs.value.length > 300) logs.value.length = 300
  }

  const foldedLogs = computed(() => {
    const folded = []
    for (const log of logs.value) {
      const last = folded[folded.length - 1]
      if (last && last.stage === log.stage && last.source === log.source && last.message === log.message) {
        last.repeat = (last.repeat || 1) + 1
        continue
      }
      folded.push({ ...log, repeat: 1 })
    }
    return folded
  })

  return { logs, foldedLogs, addLog }
}

export { logText, logTime }
