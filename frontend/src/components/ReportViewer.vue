<script setup>
// 任务报告查看器（FE-66 组件化）：自持加载/数据/下载，结论横幅与统计卡对齐三态裁决。
import { computed, onMounted, ref } from 'vue'
import { statusLabels } from '../constants'

const props = defineProps({
  analysisId: { type: String, default: '' },
  verdictReport: { type: String, default: '' },
})
const emit = defineEmits(['error'])

const loading = ref(false)
const data = ref(null)
const errorText = ref('')

onMounted(async () => {
  if (!props.analysisId) return
  loading.value = true
  try {
    const response = await fetch(`/api/tasks/${props.analysisId}/report`)
    if (!response.ok) throw new Error('报告接口不可用')
    data.value = await response.json()
  } catch (error) {
    errorText.value = '报告暂不可用，请稍后重试。'
    emit('error', '报告暂不可用。')
    console.warn(error)
  } finally {
    loading.value = false
  }
})

const reportJson = computed(() => data.value ? JSON.stringify(data.value, null, 2) : '正在加载报告…')

// 报告格式化卡（FE-22）：结论 + 统计格 + 折叠时间线
const reportCard = computed(() => {
  const doc = data.value
  if (!doc) return null
  const result = doc.result || {}
  const plan = result.dispatch_plan || {}
  const time = plan.estimated_control_time || {}
  const rounds = Array.isArray(doc.rounds) ? doc.rounds : []
  const events = Array.isArray(doc.events) ? doc.events : []
  const fireFlp = (result.fire_assessment || {}).fire_load_flp
  const initial = rounds.length && rounds[0].before ? rounds[0].before.fire_load_flp : fireFlp
  const latest = rounds.length && rounds.at(-1).after ? rounds.at(-1).after.fire_load_flp : fireFlp
  const timeWindow = time.earliest_minutes != null ? `${time.earliest_minutes}–${time.latest_minutes} 分钟` : '—'
  return {
    canControl: Boolean(plan.can_control),
    conclusion: props.verdictReport,
    statusLabel: statusLabels[doc.status] || doc.status || '—',
    stats: [
      { label: '方案版本', value: (doc.plan_versions || []).length },
      { label: '出动单元', value: (plan.selected_uavs || []).length },
      { label: '监测轮次', value: rounds.length },
      { label: '任务事件', value: events.length },
      { label: '初始 FLP', value: initial != null ? initial : '—' },
      { label: '最新 FLP', value: latest != null ? latest : '—' },
      { label: '时间区间', value: timeWindow },
      { label: '缺口项', value: (plan.resource_gap || []).length },
    ],
    events: events.slice(0, 60).map((e) => ({ time: (e.timestamp || '').slice(11, 19), stage: e.stage || '', message: e.message || '' })),
  }
})

async function downloadReport() {
  if (!props.analysisId) return
  const response = await fetch(`/api/tasks/${props.analysisId}/report/download`)
  if (!response.ok) { emit('error', '报告暂不可用。'); return }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `task-${props.analysisId}-dispatch_plan.json`
  link.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div class="report-viewer">
    <div class="report-viewer-head"><b>任务报告 · {{ analysisId }}</b><small>data/reports/{{ analysisId }}/dispatch_plan.json</small><button class="outline-btn viewer-download" @click="downloadReport">下载 JSON</button></div>
    <template v-if="errorText"><p class="report-error">{{ errorText }}</p></template>
    <template v-else-if="reportCard">
      <div :class="['report-conclusion', reportCard.canControl ? 'ok' : 'bad']"><b>{{ reportCard.conclusion }}</b><span>{{ reportCard.statusLabel }} · 数字均出自规则引擎</span></div>
      <div class="report-stats"><div v-for="s in reportCard.stats" :key="s.label" class="report-stat"><b>{{ s.value }}</b><span>{{ s.label }}</span></div></div>
      <details><summary>全链路时间线（{{ reportCard.events.length }} 条）</summary><ul class="report-events"><li v-for="(e, i) in reportCard.events" :key="i"><span class="log-time">{{ e.time }}</span><b>{{ e.stage }}</b>{{ e.message }}</li></ul></details>
      <details class="report-raw"><summary>原始 JSON</summary><pre>{{ reportJson }}</pre></details>
    </template>
    <pre v-else>{{ reportJson }}</pre>
  </div>
</template>
