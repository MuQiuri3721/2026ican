<script setup>
// 多任务对比看板（FE-68）：历史任务页勾选 ≤4 个任务，一次请求 /api/analyzes/compare
// 渲染 指标×任务 对比表。数字全部出自后端聚合（复盘档案+三态+逐轮资源），前端零计算口径。
import { computed, onMounted, ref } from 'vue'
import { formatNumber } from '../utils/labels'

const props = defineProps({
  ids: { type: Array, default: () => [] },
})
const emit = defineEmits(['error'])

const loading = ref(false)
const items = ref([])

onMounted(async () => {
  if (!props.ids.length) return
  loading.value = true
  try {
    const response = await fetch(`/api/analyzes/compare?ids=${props.ids.join(',')}`)
    if (!response.ok) throw new Error('对比接口不可用')
    items.value = await response.json().then((body) => body.items || [])
  } catch (error) {
    emit('error', '对比数据暂不可用。')
    console.warn(error)
  } finally {
    loading.value = false
  }
})

const verdictMeta = { can_control: ['可完全控制', 'ok'], maintain_only: ['可维持压制', 'mid'], cannot_control: ['不可控', 'bad'] }
const columns = computed(() => items.value.map((task) => {
  const verdict = verdictMeta[task.verdict?.verdict] || ['—', '']
  const review = task.review || {}
  return {
    id: task.analysis_id,
    time: (task.created_at || '').slice(5, 16).replace('T', ' '),
    status: task.status,
    verdictText: verdict[0],
    verdictTone: verdict[1],
    initialFlp: review.initial_flp,
    finalFlp: review.final_flp,
    delta: review.flp_delta,
    extinguished: review.extinguished,
    level: task.fire?.label || task.fire?.level || '—',
    growth: task.fire?.growth_rate,
    rounds: review.round_count,
    replans: task.replan_rounds,
    versions: review.plan_version_count,
    units: task.plan_units,
    water: task.resources?.water_liters ?? 0,
    co2: task.resources?.co2_kg ?? 0,
    people: peopleText(task.people_status),
  }
}))

function peopleText(branch) {
  return { confirmed: '有人', absent: '无人', unknown: '不确定' }[branch] || branch || '—'
}
function deltaText(value) {
  if (value == null) return '—'
  const num = Number(value)
  return `${num > 0 ? '+' : ''}${Math.round(num * 100) / 100}`
}
</script>

<template>
  <div class="compare-panel">
    <div class="compare-head"><b>多任务对比</b><span>{{ columns.length }} 个任务 · 数字出自后端复盘档案，无独立口径</span></div>
    <div v-if="loading" class="compare-loading">对比数据加载中…</div>
    <template v-else-if="columns.length">
      <div class="compare-scroll">
        <table class="compare-table">
          <thead>
            <tr><th>指标</th><th v-for="col in columns" :key="col.id">{{ col.id.slice(-8) }}<small>{{ col.time }}</small></th></tr>
          </thead>
          <tbody>
            <tr><td>三态结论</td><td v-for="col in columns" :key="col.id"><span :class="['cmp-verdict', col.verdictTone]">{{ col.verdictText }}</span></td></tr>
            <tr><td>任务状态</td><td v-for="col in columns" :key="col.id">{{ col.status }}</td></tr>
            <tr><td>火情等级</td><td v-for="col in columns" :key="col.id">{{ col.level }}</td></tr>
            <tr><td>初始 FLP</td><td v-for="col in columns" :key="col.id">{{ formatNumber(col.initialFlp) }}</td></tr>
            <tr><td>最终 FLP</td><td v-for="col in columns" :key="col.id">{{ formatNumber(col.finalFlp) }}</td></tr>
            <tr class="cmp-delta"><td>净变化</td><td v-for="col in columns" :key="col.id" :class="{ down: Number(col.delta) < 0, up: Number(col.delta) > 0 }">{{ deltaText(col.delta) }}{{ col.extinguished ? ' · 🔥已扑灭' : '' }}</td></tr>
            <tr><td>增长率</td><td v-for="col in columns" :key="col.id">{{ col.growth != null ? `${col.growth}/h` : '—' }}</td></tr>
            <tr><td>监测轮次</td><td v-for="col in columns" :key="col.id">{{ col.rounds }}</td></tr>
            <tr><td>重规划轮</td><td v-for="col in columns" :key="col.id">{{ col.replans }}</td></tr>
            <tr><td>方案版本</td><td v-for="col in columns" :key="col.id">{{ col.versions }}</td></tr>
            <tr><td>出动单元</td><td v-for="col in columns" :key="col.id">{{ col.units }}</td></tr>
            <tr><td>耗水 / 耗 C6</td><td v-for="col in columns" :key="col.id">{{ col.water }}L / {{ col.co2 }}kg</td></tr>
            <tr><td>人员口径</td><td v-for="col in columns" :key="col.id">{{ col.people }}</td></tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<style scoped>
.compare-panel{margin-top:12px;border:1px solid var(--line);border-radius:var(--radius-s);background:var(--surface);padding:12px 14px}
.compare-head{display:flex;align-items:baseline;gap:10px;margin-bottom:10px}
.compare-head b{font:700 13px var(--font-ui);color:var(--ink)}
.compare-head span{font:400 11.5px var(--font-data);color:var(--ink-3)}
.compare-loading{font:400 12.5px var(--font-ui);color:var(--ink-3);padding:10px 0}
.compare-scroll{overflow-x:auto}
.compare-table{width:100%;border-collapse:collapse;font:400 12px var(--font-data);color:var(--ink-2)}
.compare-table th,.compare-table td{border:1px solid var(--line);padding:6px 9px;text-align:left;white-space:nowrap}
.compare-table th{background:var(--surface);font:600 12px var(--font-ui);color:var(--ink)}
.compare-table th small{display:block;font:400 10.5px var(--font-data);color:var(--ink-3);margin-top:2px}
.compare-table td:first-child{font:500 12px var(--font-ui);color:var(--ink-3);background:var(--surface)}
.cmp-verdict{font-weight:600;padding:1px 8px;border-radius:999px}
.cmp-verdict.ok{color:var(--ok);background:var(--ok-soft)}
.cmp-verdict.mid{color:var(--warn);background:var(--warn-soft,var(--surface))}
.cmp-verdict.bad{color:var(--fire);background:var(--fire-soft)}
.cmp-delta td.down{color:var(--ok);font-weight:600}
.cmp-delta td.up{color:var(--fire);font-weight:600}
</style>
