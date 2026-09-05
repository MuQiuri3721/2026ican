<script setup>
// 指挥员问答（FE-22，交互范式参考 firepatrol-agents ChatPanel）：
// 基于后端 /api/tasks/{id}/chat——回答接地任务黑板摘要，数字经事后审计（⚠ 由后端附加）。
// 未接入 GLM 时走离线确定性摘要，面板照常可用。
import { nextTick, ref, watch } from 'vue'

const props = defineProps({
  taskId: { type: String, default: '' },
  enabled: { type: Boolean, default: false },
})

const history = ref([])
const input = ref('')
const busy = ref(false)
const listRef = ref(null)

// 任务切换（新研判/历史恢复/重开演训）时清空上一任务的问答历史
watch(() => props.taskId, (id, previous) => {
  if (id !== previous) { history.value = []; input.value = '' }
})

watch(() => history.value.length, async () => {
  await nextTick()
  if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight
})

async function ask() {
  const question = input.value.trim()
  if (!question || !props.taskId || busy.value) return
  busy.value = true
  history.value.push({ role: 'human', text: question })
  input.value = ''
  try {
    const response = await fetch(`/api/tasks/${props.taskId}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    })
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}))
      throw new Error(detail && detail.detail ? String(detail.detail) : `chat ${response.status}`)
    }
    const payload = await response.json()
    history.value.push({ role: 'agent', text: payload.answer || '（空回复）' })
  } catch (error) {
    const message = error instanceof Error && error.message ? error.message : ''
    history.value.push({ role: 'agent', text: `问答暂不可用：${message || '请稍后重试'}` })
    console.warn(error)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="chatpanel">
    <div class="panel-heading">
      <h2>指挥员问答</h2>
      <span :class="['llm-tag', { on: enabled }]">{{ enabled ? 'GLM 已接入' : '离线规则模式' }}</span>
    </div>
    <div ref="listRef" class="chat-history">
      <div v-if="!history.length" class="chat-empty">
        向智能参谋提问当前任务，例如：为什么出动这 2 架灭火机？现在火势控制住了吗？水剂还剩多少？回答基于任务实时数据，数字以面板为准。
      </div>
      <div v-for="(qa, i) in history" :key="i" :class="['chat-bubble', qa.role]">
        <span class="chat-who">{{ qa.role === 'human' ? '问' : '答' }}</span>
        <p>{{ qa.text }}</p>
      </div>
      <div v-if="busy" class="chat-bubble agent typing"><span class="chat-who">答</span><p>思考中…</p></div>
    </div>
    <div class="chat-input-row">
      <input
        v-model="input"
        :disabled="!taskId || busy"
        :placeholder="taskId ? '输入问题，回车发送…' : '完成一次研判后可提问'"
        aria-label="向智能参谋提问"
        maxlength="200"
        @keydown.enter="ask"
      >
      <button class="primary chat-send" :disabled="!taskId || busy || !input.trim()" @click="ask">发送</button>
    </div>
  </div>
</template>
