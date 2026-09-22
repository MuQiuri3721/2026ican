<script setup>
// 历史任务面板（B-8 第二波组件化）：任务列表 + 对比勾选 + ComparePanel 挂载。
// 列表数据由父级拉取（props.tasks），行恢复/刷新以事件上抛——任务编排仍归 App。
// UI-REDESIGN（2026-09）：对齐设计稿「任务管理」双栏——左任务列表，右任务详情
// （任务全流程/方案要点/历史方案版本/关键事件/轮次执行结果）。行点击=恢复主显示的契约不变，
// 详情走独立「详情」按钮在页内展开。
import { computed, ref, watch } from 'vue'
import { ChevronRight, ClipboardList, RefreshCw } from 'lucide-vue-next'
import ComparePanel from './ComparePanel.vue'

defineProps({
  tasks: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['restore', 'refresh', 'error'])

function statusLabel(status) {
  return { completed: '已完成', succeeded: '已完成', executing: '执行中', running: '执行中', awaiting_confirmation: '待确认', approved: '已批准', replanning: '重规划中', terminated: '已终止', failed: '失败' }[status] || status || '—'
}
function statusTone(status) {
  if (['completed', 'succeeded'].includes(status)) return 'ok'
  if (['executing', 'running', 'approved', 'replanning'].includes(status)) return 'blue'
  if (status === 'awaiting_confirmation') return 'orange'
  if (['terminated', 'failed'].includes(status)) return 'red'
  return 'slate'
}

const compareSel = ref([])
const compareOpen = ref(false)
watch(compareSel, (next) => {
  if (next.length > 4) compareSel.value = next.slice(-4)
  if (next.length < 2) compareOpen.value = false
})

// —— 任务详情（设计稿右栏）——
const detail = ref(null)
const detailLoading = ref(false)
async function openDetail(task) {
  if (!task?.analysis_id) return
  detailLoading.value = true
  try {
    const response = await fetch(`/api/analyze/${task.analysis_id}`)
    if (!response.ok) throw new Error('详情获取失败')
    detail.value = await response.json()
  } catch (error) {
    emit('error', '任务详情暂不可用。')
    console.warn(error)
  } finally {
    detailLoading.value = false
  }
}
const detailStages = computed(() => (detail.value?.stages || []).map((stage, index) => ({
  no: index + 1,
  label: stage.label || stage.stage || stage.name || `阶段 ${index + 1}`,
  time: (stage.timestamp || stage.time || '').slice(11, 19) || '',
})))
const detailVersions = computed(() => (detail.value?.plan_versions || []).map((version) => ({
  label: `V${version.plan_version}`,
  time: (version.created_at || version.timestamp || '').slice(5, 16).replace('T', ' ') || '—',
  status: version.status || '—',
})))
const detailRounds = computed(() => (detail.value?.rounds || []).map((round, index) => ({
  no: round.round || round.monitor_round || index + 1,
  before: round.before?.fire_load_flp ?? '—',
  after: round.after?.fire_load_flp ?? round.after?.flp ?? '—',
  action: round.next_action === 'awaiting_confirmation' ? '等待二次审批' : round.next_action === 'finish' ? '火情扑灭' : (round.next_action || '保持观察'),
})))
const detailEvents = computed(() => (detail.value?.events || detail.value?.logs || []).slice(0, 8))
</script>

<template>
  <section class="detail-view history-view">
    <div class="detail-heading"><div><h2>任务列表</h2><p>任务记录来自后端 /api/analyzes，点击任务可恢复主显示结果，点「详情」在本页查看全流程。勾选 2–4 个任务可横向对比。{{ tasks.length > 50 ? " 最近 50 条优先显示" : "" }}</p></div><button v-if="compareSel.length >= 2" class="outline-btn" @click="compareOpen = !compareOpen">{{ compareOpen ? '收起对比' : `对比所选（${compareSel.length}）` }}</button><button class="outline-btn" @click="emit('refresh')"><RefreshCw :size="14" /> 刷新</button></div>
    <ComparePanel v-if="compareOpen && compareSel.length >= 2" :ids="compareSel" @error="emit('error', $event)" />
    <div class="history-two-col">
      <div class="full-logs history-list">
        <div v-if="loading"><div class="skeleton-row"></div><div class="skeleton-row"></div><div class="skeleton-row"></div></div>
        <div v-else-if="!tasks.length" class="empty-hint"><b>还没有历史任务</b>点击右上角「开始任务」上传影像，完成研判后任务会自动归档到这里。</div>
        <div v-for="task in tasks.slice(0, 50)" :key="task.analysis_id" class="history-row" @click="emit('restore', task)"><label class="cmp-pick" title="勾选参与对比（2–4 个）" @click.stop><input type="checkbox" :value="task.analysis_id" v-model="compareSel"><span>比</span></label><div class="hr-main"><span class="hr-title"><strong>{{ task.analysis_id }}</strong><small>{{ task.input?.image_name || task.input?.scene_id || '演训模拟' }}</small></span><span class="log-time">{{ task.created_at?.slice(0, 19).replace('T', ' ') }}<i v-if="task.input?.longitude != null" class="hr-loc">{{ task.input.longitude }}°E · {{ task.input.latitude }}°N</i></span></div><span :class="['dt-chip', 'hr-chip', statusTone(task.status)]">{{ statusLabel(task.status) }}</span><span class="hr-actions"><button class="outline-btn hr-detail" title="在本页查看任务全流程/方案版本/轮次" @click.stop="openDetail(task)"><ClipboardList :size="13" /> 详情</button><span class="hr-go"><ChevronRight :size="15" /></span></span></div>
      </div>
      <aside class="history-detail" aria-label="任务详情">
        <div v-if="detailLoading" class="skeleton-row"></div>
        <template v-else-if="detail">
          <div class="hd-head"><b>任务详情</b><span class="hr-title"><strong>{{ detail.analysis_id }}</strong><small>{{ detail.input?.image_name || detail.input?.scene_id || '演训模拟' }}</small></span><span :class="['dt-chip', statusTone(detail.status)]">{{ statusLabel(detail.status) }}</span></div>
          <div class="hd-block"><b>任务全流程</b><div v-if="detailStages.length" class="hd-steps"><div v-for="stage in detailStages" :key="stage.no" class="hd-step"><i>{{ stage.no }}</i><div><span>{{ stage.label }}</span><small>{{ stage.time }}</small></div></div></div><div v-else class="hd-empty">该任务未记录阶段轨迹。</div></div>
          <div class="hd-block"><b>方案要点</b><p class="hd-explain">{{ detail.result?.explanation || '—' }}</p><table v-if="detailVersions.length" class="data-table"><thead><tr><th>版本</th><th>生成时间</th><th>状态</th></tr></thead><tbody><tr v-for="version in detailVersions" :key="version.label"><td class="num"><b>{{ version.label }}</b></td><td>{{ version.time }}</td><td><span class="dt-chip slate">{{ version.status }}</span></td></tr></tbody></table></div>
          <div class="hd-block" v-if="detailRounds.length"><b>轮次执行结果</b><table class="data-table"><thead><tr><th>轮次</th><th class="num">轮前 FLP</th><th class="num">轮后 FLP</th><th>动作</th></tr></thead><tbody><tr v-for="row in detailRounds" :key="row.no"><td class="num"><b>#{{ row.no }}</b></td><td class="num">{{ row.before }}</td><td class="num">{{ row.after }}</td><td>{{ row.action }}</td></tr></tbody></table></div>
          <div class="hd-block"><b>关键事件</b><div v-if="detailEvents.length" class="hd-events"><div v-for="(event, index) in detailEvents" :key="index" class="hd-event"><span class="log-time">{{ (event.timestamp || '').slice(11, 19) }}</span><p>{{ event.message || event.text }}</p></div></div><div v-else class="hd-empty">暂无事件记录。</div></div>
          <a v-if="detail.analysis_id" class="outline-btn" :href="`/api/tasks/${detail.analysis_id}/report/export`" download>导出图文报告</a>
        </template>
        <div v-else class="hd-empty hd-placeholder"><b>未选择任务</b>点击左侧任务行的「详情」查看任务全流程、方案版本与轮次执行结果；点击行其他区域可恢复该任务为主显示。</div>
      </aside>
    </div>
  </section>
</template>
