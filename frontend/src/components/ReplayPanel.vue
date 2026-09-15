<script setup>
// 推演回放面板（FE-67 复盘层）：逐轮回放轮次快照——FLP 账本/触发器/机群状态。
// 数据全部来自 rounds[].before/after（BE-13 起每轮已存全量快照），零后端依赖。
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, Pause, Play, Rewind } from 'lucide-vue-next'
import { statusLabels } from '../constants'
import { formatNumber } from '../utils/labels'

const props = defineProps({
  rounds: { type: Array, default: () => [] },
  areaPerFlp: { type: Number, default: 0 },
})

const open = ref(false)
const index = ref(0)
const playing = ref(false)
let timer = null

const current = computed(() => props.rounds[index.value] || null)
const ledger = computed(() => (current.value?.after?.flp_ledger) || null)
const perMinute = computed(() => (ledger.value?.per_minute) || [])
const fleetRows = computed(() => (current.value?.after?.fleet) || [])
const triggers = computed(() => current.value?.replan_triggers || [])
const netFlp = computed(() => {
  if (ledger.value && ledger.value.net_change_flp != null) return ledger.value.net_change_flp
  const after = current.value?.after?.fire_load_flp
  const before = current.value?.before?.fire_load_flp
  return after != null && before != null ? Math.round((after - before) * 100) / 100 : null
})
const areaM2 = computed(() => {
  const after = current.value?.after?.fire_load_flp
  return after != null && props.areaPerFlp ? Math.round(after * props.areaPerFlp) : null
})
const actionText = computed(() => {
  const action = current.value?.next_action
  if (action === 'finish') return '火情扑灭 · 结案'
  if (action === 'awaiting_confirmation') return '等待二次审批'
  const names = { continue: '继续压制', resupply: '补给循环', reinforce: '请求增援', return: '返航整备' }
  return names[action] || action || '—'
})

// 逐分钟 FLP 火花线：账本 per_minute 的 after 序列归一化到 100×30 视窗
const spark = computed(() => {
  const points = perMinute.value.map((m) => Number(m.after_flp ?? m.after ?? 0)).filter((v) => Number.isFinite(v))
  if (points.length < 2) return ''
  const min = Math.min(...points)
  const max = Math.max(...points)
  const span = max - min || 1
  return points.map((v, i) => `${(i / (points.length - 1)) * 100},${28 - ((v - min) / span) * 24}`).join(' ')
})

function stopTimer() {
  if (timer) { clearInterval(timer); timer = null }
  playing.value = false
}
function togglePlay() {
  if (playing.value) { stopTimer(); return }
  if (index.value >= props.rounds.length - 1) index.value = 0
  playing.value = true
  timer = setInterval(() => {
    if (index.value >= props.rounds.length - 1) { stopTimer(); return }
    index.value += 1
  }, 1600)
}
function step(delta) {
  stopTimer()
  index.value = Math.min(Math.max(index.value + delta, 0), props.rounds.length - 1)
}
watch(() => props.rounds.length, (len) => {
  if (index.value > len - 1) { stopTimer(); index.value = Math.max(len - 1, 0) }
})
onBeforeUnmount(stopTimer)
</script>

<template>
  <div class="replay-panel">
    <button class="replay-head" @click="open = !open">
      <Rewind :size="14" />
      <b>推演回放</b>
      <span>{{ rounds.length }} 轮快照 · 复盘逐轮态势</span>
      <i>{{ open ? '收起' : '展开' }}</i>
    </button>
    <div v-if="open" class="replay-body">
      <div class="replay-controls">
        <button class="replay-btn" title="上一轮" @click="step(-1)"><ChevronLeft :size="15" /></button>
        <button class="replay-btn play" :title="playing ? '暂停' : '播放'" @click="togglePlay">
          <Pause v-if="playing" :size="15" /><Play v-else :size="15" />
        </button>
        <button class="replay-btn" title="下一轮" @click="step(1)"><ChevronRight :size="15" /></button>
        <div class="replay-ticks">
          <button v-for="(r, i) in rounds" :key="r.round || i" :class="['tick', { on: i === index, good: r.next_action === 'finish' }]"
                  :title="`第 ${r.round || i + 1} 轮`" @click="stopTimer(); index = i">{{ r.round || i + 1 }}</button>
        </div>
        <span class="replay-pos">第 {{ current?.round || index + 1 }} / {{ rounds.length }} 轮</span>
      </div>
      <template v-if="current">
        <div class="replay-kpis">
          <div class="rk"><span>FLP before → after</span><b>{{ formatNumber(current.before?.fire_load_flp) }} → {{ formatNumber(current.after?.fire_load_flp) }}</b></div>
          <div class="rk" :class="netFlp < 0 ? 'down' : netFlp > 0 ? 'up' : ''"><span>净变化</span><b>{{ netFlp != null ? (netFlp > 0 ? '+' : '') + netFlp : '—' }}</b></div>
          <div class="rk"><span>增长 / 压制</span><b>{{ ledger ? `${formatNumber(ledger.growth_flp)} / ${formatNumber(ledger.suppression_flp)}` : '—' }}</b></div>
          <div v-if="areaM2 != null" class="rk"><span>过火面积≈</span><b>{{ areaM2 }} m²</b></div>
          <div class="rk"><span>动作</span><b>{{ actionText }}</b></div>
        </div>
        <div class="replay-mid">
          <div v-if="spark" class="replay-spark">
            <span class="spark-title">逐分钟 FLP（本轮 {{ perMinute.length }} min）</span>
            <svg viewBox="0 0 100 30" preserveAspectRatio="none"><polyline :points="spark" fill="none" stroke="currentColor" stroke-width="1.6" vector-effect="non-scaling-stroke" /></svg>
          </div>
          <div class="replay-meta">
            <span v-if="triggers.length" class="r-trigger">触发：{{ triggers.join('、') }}</span>
            <span v-else class="r-calm">本轮无重规划触发</span>
            <span v-if="current.observation_adjustment_flp">观测校正 {{ current.observation_adjustment_flp }} FLP</span>
          </div>
        </div>
        <div class="replay-fleet">
          <div v-for="u in fleetRows" :key="u.uav_id || u.id" class="rf" :class="'p-' + (u.status || 'available')">
            <b>{{ u.uav_id || u.id }}</b>
            <span :class="{ low: (u.soc ?? 100) < 30 }">SOC {{ Math.round(u.soc ?? 0) }}%</span>
            <em>{{ statusLabels[u.status] || u.status || '待命' }}</em>
            <small v-if="u.agent_remaining > 0">{{ Math.round(u.agent_remaining * 10) / 10 }}{{ u.agent_unit === 'kg' ? 'kg' : 'L' }}</small>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.replay-panel{margin-top:12px;border:1px solid var(--line);border-radius:var(--radius-s);background:var(--surface);overflow:hidden}
.replay-head{display:flex;align-items:center;gap:8px;width:100%;border:0;background:transparent;padding:10px 13px;cursor:pointer;font:inherit;color:var(--ink-2)}
.replay-head b{font:700 13px var(--font-ui);color:var(--ink)}
.replay-head span{font:400 11.5px var(--font-data);color:var(--ink-3)}
.replay-head i{margin-left:auto;font:500 11.5px var(--font-ui);font-style:normal;color:var(--accent)}
.replay-body{padding:0 13px 13px;display:flex;flex-direction:column;gap:10px}
.replay-controls{display:flex;align-items:center;gap:8px}
.replay-btn{display:grid;place-items:center;width:28px;height:28px;border:1px solid var(--line-strong);border-radius:50%;background:transparent;color:var(--ink-2);cursor:pointer}
.replay-btn:hover{color:var(--accent);border-color:var(--accent-line)}
.replay-btn.play{background:var(--accent-soft);border-color:var(--accent-line);color:var(--accent)}
.replay-ticks{display:flex;gap:4px;flex-wrap:wrap}
.tick{min-width:24px;padding:2px 5px;border:1px solid var(--line);border-radius:999px;background:transparent;font:500 11px var(--font-data);color:var(--ink-3);cursor:pointer}
.tick.on{background:var(--accent);border-color:var(--accent);color:#fff}
.tick.good{border-color:var(--ok-line);color:var(--ok)}
.replay-pos{margin-left:auto;font:500 12px var(--font-data);color:var(--ink-2);white-space:nowrap}
.replay-kpis{display:flex;gap:8px;flex-wrap:wrap}
.rk{flex:1 1 120px;padding:8px 10px;border:1px solid var(--line);border-radius:var(--radius-s);display:flex;flex-direction:column;gap:2px}
.rk span{font:400 11px var(--font-data);color:var(--ink-3);white-space:nowrap}
.rk b{font:700 13.5px var(--font-data);color:var(--ink)}
.rk.down b{color:var(--ok)}
.rk.up b{color:var(--fire)}
.replay-mid{display:flex;gap:12px;align-items:stretch;flex-wrap:wrap}
.replay-spark{flex:1 1 200px;color:var(--accent)}
.spark-title{display:block;font:400 11px var(--font-data);color:var(--ink-3);margin-bottom:3px}
.replay-spark svg{width:100%;height:34px;display:block}
.replay-meta{flex:1 1 180px;display:flex;flex-direction:column;gap:5px;justify-content:center}
.replay-meta span{font:400 12px var(--font-data);color:var(--ink-2)}
.r-trigger{color:var(--warn)!important}
.r-calm{color:var(--ink-3)!important}
.replay-fleet{display:grid;grid-template-columns:repeat(auto-fill,minmax(96px,1fr));gap:6px}
.rf{display:flex;flex-direction:column;gap:1px;padding:6px 8px;border:1px solid var(--line);border-left:3px solid var(--line-strong);border-radius:var(--radius-s)}
.rf b{font:700 12px var(--font-data);color:var(--ink)}
.rf span{font:400 11px var(--font-data);color:var(--ink-2)}
.rf span.low{color:var(--fire);font-weight:600}
.rf em{font:400 10.5px var(--font-ui);font-style:normal;color:var(--ink-3)}
.rf small{font:400 10.5px var(--font-data);color:var(--ink-3)}
.rf.p-working{border-left-color:var(--accent)}
.rf.p-flying,.rf.p-returning{border-left-color:var(--plan,var(--accent))}
.rf.p-fault{border-left-color:var(--fire)}
.rf.p-charging,.rf.p-servicing{border-left-color:var(--warn)}
</style>
