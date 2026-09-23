<script setup>
// 任务归档面板（UI-REDESIGN 2026-09-23 参考图样式）：编号/报警时间/火情等级/过火面积/
// 人员状态/处置结论/耗时/状态 的归档行表 + 状态筛选 + 右侧任务详情。
// 列表数据由父级拉取（props.tasks，slim 信封含 summary 摘要），行恢复/刷新以事件上抛——
// 任务编排仍归 App。行点击=恢复主显示的契约不变；e2e 依赖 .history-row 类名，保留在数据行上。
import { computed, ref, watch } from 'vue'
import { ChevronRight, ClipboardList, RefreshCw } from 'lucide-vue-next'
import ComparePanel from './ComparePanel.vue'

const props = defineProps({
  tasks: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['restore', 'refresh', 'error'])

function statusLabel(status) {
  return { completed: '已完成', succeeded: '已完成', executing: '执行中', running: '执行中', awaiting_confirmation: '待确认', approved: '已批准', replanning: '重规划中', terminated: '已终止', failed: '失败', created: '待研判', pending: '待研判', analyzing: '研判中' }[status] || status || '—'
}
function statusTone(status) {
  if (['completed', 'succeeded'].includes(status)) return 'ok'
  if (['executing', 'running', 'approved', 'replanning'].includes(status)) return 'blue'
  if (status === 'awaiting_confirmation') return 'orange'
  if (['terminated', 'failed'].includes(status)) return 'red'
  return 'slate'
}

// —— 归档筛选（设计稿任务状态：待研判/待确认/执行中/重规划中/已完成/已终止/失败）——
const ACTIVE_STATUSES = ['executing', 'running', 'approved', 'replanning', 'awaiting_confirmation', 'analyzing', 'created', 'pending']
const FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'active', label: '进行中' },
  { key: 'completed', label: '已完成' },
  { key: 'terminated', label: '已终止' },
]
const activeFilter = ref('all')
const recent = computed(() => props.tasks.slice(0, 50))
const filterCounts = computed(() => {
  const counts = { all: recent.value.length, active: 0, completed: 0, terminated: 0 }
  for (const task of recent.value) {
    if (ACTIVE_STATUSES.includes(task.status)) counts.active += 1
    else if (['completed', 'succeeded'].includes(task.status)) counts.completed += 1
    else if (task.status === 'terminated') counts.terminated += 1
  }
  return counts
})
const filteredTasks = computed(() => {
  if (activeFilter.value === 'active') return recent.value.filter((task) => ACTIVE_STATUSES.includes(task.status))
  if (activeFilter.value === 'completed') return recent.value.filter((task) => ['completed', 'succeeded'].includes(task.status))
  if (activeFilter.value === 'terminated') return recent.value.filter((task) => task.status === 'terminated')
  return recent.value
})

// 归档编号：同年任务按时间先后编 001、002……（如 2026001），纯展示层编号
const taskNo = computed(() => {
  const map = new Map()
  const perYear = {}
  for (const task of [...props.tasks].reverse()) {
    const year = (task.created_at || '').slice(0, 4) || '0000'
    perYear[year] = (perYear[year] || 0) + 1
    map.set(task.analysis_id, `${year}${String(perYear[year]).padStart(3, '0')}`)
  }
  return map
})

// —— 行内摘要展示（slim summary；全局色规：红=危险 黄=待定 绿=正常）——
const VERDICTS = {
  can_control: { label: '可控制', tone: 'ok' },
  maintain_only: { label: '维持压制', tone: 'warn' },
  cannot_control: { label: '不可控制·需增援', tone: 'red' },
}
const PEOPLE = {
  confirmed: { label: '有人', tone: 'red' },
  absent: { label: '无人', tone: 'ok' },
  unknown: { label: '不确定', tone: 'warn' },
}
function levelView(task) {
  const summary = task.summary || {}
  const level = Number(summary.level)
  if (!summary.level_label || !Number.isFinite(level)) return { short: '待研判', tone: 'slate', full: '尚未完成火情研判' }
  return { short: String(summary.level_label).split('·')[0].trim(), tone: `lv${level}`, full: summary.level_label }
}
function verdictView(task) {
  return VERDICTS[task.summary?.control_verdict] || { label: '—', tone: 'slate' }
}
function peopleView(task) {
  return PEOPLE[task.summary?.people_status] || { label: '—', tone: 'slate' }
}
function fmtClock(iso) {
  return (iso || '').slice(5, 16).replace('T', ' ') || '—'
}
function fmtArea(m2) {
  const value = Number(m2)
  if (m2 == null || !Number.isFinite(value)) return '—'
  return value >= 10000 ? `${(value / 10000).toFixed(2)} ha` : `${Math.round(value)} m²`
}
function fmtDuration(task) {
  const start = Date.parse(task.created_at || '')
  const end = Date.parse(task.updated_at || '')
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return '—'
  const seconds = Math.round((end - start) / 1000)
  if (seconds < 60) return `${seconds} 秒`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
  return `${Math.floor(seconds / 3600)} 时 ${Math.floor((seconds % 3600) / 60)} 分`
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
    <div class="detail-heading"><div><h2>任务归档</h2><p>任务完成研判后自动编号归档。点击行恢复任务至主显示，「详情」查看全流程，勾选 2–4 项可横向对比。{{ tasks.length > 50 ? " 最近 50 条优先显示" : "" }}</p></div><button v-if="compareSel.length >= 2" class="outline-btn" @click="compareOpen = !compareOpen">{{ compareOpen ? '收起对比' : `对比所选（${compareSel.length}）` }}</button><button class="outline-btn" @click="emit('refresh')"><RefreshCw :size="14" /> 刷新</button></div>
    <ComparePanel v-if="compareOpen && compareSel.length >= 2" :ids="compareSel" @error="emit('error', $event)" />
    <div class="history-two-col">
      <div class="full-logs history-list archive-list">
        <div v-if="loading"><div class="skeleton-row"></div><div class="skeleton-row"></div><div class="skeleton-row"></div></div>
        <div v-else-if="!tasks.length" class="empty-hint"><b>还没有归档任务</b>到「火情监测」上传影像或开始演训，完成研判后任务会自动归档到这里。</div>
        <template v-else>
          <div class="arc-filters"><button v-for="filter in FILTERS" :key="filter.key" :class="['arc-filter', { on: activeFilter === filter.key }]" @click="activeFilter = filter.key">{{ filter.label }}<i>{{ filterCounts[filter.key] }}</i></button></div>
          <div class="arc-head arc-grid"><span class="ah-pick" title="勾选参与对比">比</span><span>编号</span><span>报警时间</span><span>火情等级</span><span>过火面积</span><span>人员状态</span><span>处置结论</span><span>耗时</span><span>状态</span><span></span></div>
          <div v-for="task in filteredTasks" :key="task.analysis_id" class="arc-row history-row arc-grid" :title="`点击恢复 ${task.analysis_id} 为主显示`" @click="emit('restore', task)"><label class="cmp-pick" title="勾选参与对比（2–4 个）" @click.stop><input type="checkbox" :value="task.analysis_id" v-model="compareSel"><span>比</span></label><strong class="arc-no">{{ taskNo.get(task.analysis_id) }}</strong><span class="arc-time">{{ fmtClock(task.created_at) }}</span><span :class="['arc-lv', levelView(task).tone]" :title="levelView(task).full">{{ levelView(task).short }}</span><span class="arc-area">{{ fmtArea(task.summary?.fire_area_m2) }}</span><span :class="['dt-chip', 'arc-mini', peopleView(task).tone]">{{ peopleView(task).label }}</span><span :class="['dt-chip', 'arc-mini', verdictView(task).tone]">{{ verdictView(task).label }}</span><span class="arc-dur">{{ fmtDuration(task) }}</span><span :class="['dt-chip', 'hr-chip', statusTone(task.status)]">{{ statusLabel(task.status) }}</span><span class="hr-actions"><button class="outline-btn hr-detail" title="在本页查看任务全流程/方案版本/轮次" @click.stop="openDetail(task)"><ClipboardList :size="13" /> 详情</button><span class="hr-go"><ChevronRight :size="15" /></span></span></div>
          <div v-if="!filteredTasks.length" class="empty-hint"><b>该状态下暂无任务</b>切换上方筛选条件，或到「火情监测」开始新的研判。</div>
        </template>
      </div>
      <aside class="history-detail" aria-label="任务详情">
        <div v-if="detailLoading" class="skeleton-row"></div>
        <template v-else-if="detail">
          <div class="hd-head"><b>任务详情</b><span class="hr-title"><strong>{{ taskNo.get(detail.analysis_id) || detail.analysis_id }}</strong><small>{{ detail.input?.image_name || detail.input?.scene_id || '演训模拟' }}</small></span><span :class="['dt-chip', statusTone(detail.status)]">{{ statusLabel(detail.status) }}</span></div>
          <div class="hd-block"><b>任务全流程</b><div v-if="detailStages.length" class="hd-steps"><div v-for="stage in detailStages" :key="stage.no" class="hd-step"><i>{{ stage.no }}</i><div><span>{{ stage.label }}</span><small>{{ stage.time }}</small></div></div></div><div v-else class="hd-empty">该任务未记录阶段轨迹。</div></div>
          <div class="hd-block"><b>方案要点</b><p class="hd-explain">{{ detail.result?.explanation || '—' }}</p><table v-if="detailVersions.length" class="data-table"><thead><tr><th>版本</th><th>生成时间</th><th>状态</th></tr></thead><tbody><tr v-for="version in detailVersions" :key="version.label"><td class="num"><b>{{ version.label }}</b></td><td>{{ version.time }}</td><td><span class="dt-chip slate">{{ version.status }}</span></td></tr></tbody></table></div>
          <div class="hd-block" v-if="detailRounds.length"><b>轮次执行结果</b><table class="data-table"><thead><tr><th>轮次</th><th class="num">轮前 FLP</th><th class="num">轮后 FLP</th><th>动作</th></tr></thead><tbody><tr v-for="row in detailRounds" :key="row.no"><td class="num"><b>#{{ row.no }}</b></td><td class="num">{{ row.before }}</td><td class="num">{{ row.after }}</td><td>{{ row.action }}</td></tr></tbody></table></div>
          <div class="hd-block"><b>关键事件</b><div v-if="detailEvents.length" class="hd-events"><div v-for="(event, index) in detailEvents" :key="index" class="hd-event"><span class="log-time">{{ (event.timestamp || '').slice(11, 19) }}</span><p>{{ event.message || event.text }}</p></div></div><div v-else class="hd-empty">暂无事件记录。</div></div>
          <a v-if="detail.analysis_id" class="outline-btn" :href="`/api/tasks/${detail.analysis_id}/report/export`" download>导出图文报告</a>
        </template>
        <div v-else class="hd-empty hd-placeholder"><b>未选择任务</b>点击左侧归档行的「详情」查看任务全流程、方案版本与轮次执行结果；点击行其他区域可恢复该任务为主显示。</div>
      </aside>
    </div>
  </section>
</template>
