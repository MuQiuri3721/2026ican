<script setup>
// 火情演化时间轴（FE-19，交互范式参考 firepatrol-agents RoundTimeline）：
// 逐轮 after FLP 曲线 + 渐变面积；触发重规划的轮次金色打点；最新点脉动。数据全部来自后端 rounds。
import { computed } from 'vue'

const props = defineProps({
  rounds: { type: Array, default: () => [] },
})

const W = 760
const H = 170
const PAD_L = 40
const PAD_R = 16
const PAD_T = 14
const PAD_B = 24

const series = computed(() => {
  const values = []
  for (const round of props.rounds) {
    const v = Number(round.after && (round.after.fire_load_flp ?? round.after.flp))
    if (!Number.isFinite(v)) continue
    values.push({
      v,
      round: round.round || round.monitor_round || values.length + 1,
      before: round.before ? (round.before.fire_load_flp ?? round.before.flp) : null,
      event: Boolean((round.replan_triggers || round.replan_trigger || []).length),
    })
  }
  if (!values.length) return null
  const max = Math.max(...values.map((p) => p.v), 1)
  const pts = values.map((p, i) => ({
    ...p,
    x: PAD_L + (values.length === 1 ? 0 : (i / (values.length - 1)) * (W - PAD_L - PAD_R)),
    y: H - PAD_B - (p.v / max) * (H - PAD_T - PAD_B),
  }))
  const fmt = (n) => Number(n).toFixed(1)
  let line = `M${fmt(pts[0].x)},${fmt(pts[0].y)}`
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1]
    const b = pts[i]
    line += ` Q${fmt(a.x)},${fmt(a.y)} ${fmt((a.x + b.x) / 2)},${fmt((a.y + b.y) / 2)}`
  }
  const last = pts[pts.length - 1]
  line += ` T${fmt(last.x)},${fmt(last.y)}`
  const first = pts[0]
  return {
    pts,
    line,
    max,
    area: `${line} L${fmt(last.x)},${H - PAD_B} L${fmt(first.x)},${H - PAD_B} Z`,
    first,
    last,
    statText: `第 ${last.round} 轮 · B ${last.before == null ? '—' : last.before} → ${last.v}`,
  }
})
</script>

<template>
  <div class="evo-panel">
    <div class="evo-head">
      <b>火情演化 · FLP</b>
      <span v-if="series" class="evo-stat">{{ series.statText }}</span>
    </div>
    <svg
      v-if="series"
      class="evo-svg"
      :viewBox="`0 0 ${W} ${H}`"
      preserveAspectRatio="none"
      role="img"
      aria-label="火情负荷逐轮演化曲线"
    >
      <defs>
        <linearGradient id="evoFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#e07856" stop-opacity="0.32" />
          <stop offset="100%" stop-color="#e07856" stop-opacity="0.02" />
        </linearGradient>
      </defs>
      <g v-for="f in [0, 0.5, 1]" :key="f">
        <line
          :x1="PAD_L"
          :x2="W - PAD_R"
          :y1="H - PAD_B - f * (H - PAD_T - PAD_B)"
          :y2="H - PAD_B - f * (H - PAD_T - PAD_B)"
          stroke="#20302a"
          :stroke-dasharray="f === 0 ? '' : '3 5'"
        />
        <text :x="6" :y="H - PAD_B - f * (H - PAD_T - PAD_B) + 3" fill="#5f7268" font-size="9">
          {{ (series.max * f).toFixed(0) }}
        </text>
      </g>
      <path :d="series.area" fill="url(#evoFill)" />
      <path :d="series.line" fill="none" stroke="#e07856" stroke-width="2.2" stroke-linecap="round" />
      <g v-for="p in series.pts" :key="p.round">
        <circle v-if="p.event" :cx="p.x" :cy="p.y" r="7" fill="none" stroke="#e2b95d" stroke-opacity="0.45" />
        <circle :cx="p.x" :cy="p.y" :r="p.event ? 4 : 3" :fill="p.event ? '#e2b95d' : '#e07856'" />
      </g>
      <text :x="series.first.x" :y="H - 7" fill="#5f7268" font-size="9" text-anchor="middle">R{{ series.first.round }}</text>
      <text :x="series.last.x" :y="H - 7" fill="#5f7268" font-size="9" text-anchor="middle">R{{ series.last.round }}</text>
      <circle :cx="series.last.x" :cy="series.last.y" r="8" fill="none" stroke="#e07856" stroke-opacity="0.4">
        <animate attributeName="r" values="6;11;6" dur="2s" repeatCount="indefinite" />
        <animate attributeName="stroke-opacity" values="0.5;0;0.5" dur="2s" repeatCount="indefinite" />
      </circle>
    </svg>
    <div v-else class="evo-empty">方案获批后，火情负荷将按 5 分钟轮次在此逐轮演化；触发重规划的轮次会以金色打点标注。</div>
  </div>
</template>
