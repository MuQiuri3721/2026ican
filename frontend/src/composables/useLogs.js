import { computed, ref } from 'vue'
import { logText, logTime } from '../utils/labels'

export function useLogs(initial = []) {
  const logs = ref(initial)

  function addLog(message, details = {}) {
    logs.value.unshift({ timestamp: new Date().toISOString(), stage: 'ui', source: 'frontend', message, ...details })
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
