<script setup>
// 过火面积趋势（数据分析页 · 设计稿双趋势图之一）：逐轮过火面积曲线 + 渐变面积。
// 面积口径与 ReplayPanel 一致——after.next_fire_area_m2 优先，缺失时按 FLP×area_per_flp 换算。
import { computed } from 'vue'
import { formatNumber } from '../utils/labels'

const props = defineProps({
  rounds: { type: Array, default: () => [] },
  areaPerFlp: { type: Number, default: 0 },
})

const W = 760
const H = 170
const PAD_L = 46
const PAD_R = 46
const PAD_T = 22
const PAD_B = 26

const series = computed(() => {
  const values = []
  for (const round of props.rounds) {
    const after = round.after || {}
    const flp = Number(after.fire_load_flp ?? after.flp)
    let area = Number(after.next_fire_area_m2 ?? after.fire_area_m2)
    if (!Number.isFinite(area) && Number.isFinite(flp) && props.areaPerFlp) area = flp * props.areaPerFlp
    if (!Number.isFinite(area)) continue
    values.push({
      v: area,
      round: round.round || round.monitor_round || values.length + 1,
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
  const peak = pts.reduce((a, b) => (b.v > a.v ? b : a), pts[0])
  return {
    pts,
    line,
    max,
    peak,
    first,
    last,
    area: `${line} L${fmt(last.x)},${H - PAD_B} L${fmt(first.x)},${H - PAD_B} Z`,
    statText: `第 ${last.round} 轮 · ${formatNumber(last.v)} m²（峰值 ${formatNumber(peak.v)} m²）`,
  }
})
</script>

<template>
  <div class="evo-panel area-panel">
    <div class="evo-head">
      <b>过火面积趋势 · m²</b>
      <span v-if="series" class="evo-stat">{{ series.statText }}</span>
    </div>
    <svg v-if="series" class="evo-svg" :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" role="img" aria-label="过火面积逐轮演化曲线">
      <defs>
        <linearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#d9541e" stop-opacity="0.3" />
          <stop offset="100%" stop-color="#d9541e" stop-opacity="0.02" />
        </linearGradient>
      </defs>
      <g v-for="f in [0, 0.5, 1]" :key="f">
        <line :x1="PAD_L" :x2="W - PAD_R" :y1="H - PAD_B - f * (H - PAD_T - PAD_B)" :y2="H - PAD_B - f * (H - PAD_T - PAD_B)" stroke="#20302a" :stroke-dasharray="f === 0 ? '' : '3 5'" />
        <text :x="6" :y="H - PAD_B - f * (H - PAD_T - PAD_B) + 3" fill="#5f7268" font-size="9">{{ formatNumber(series.max * f) }}</text>
      </g>
      <path :d="series.area" fill="url(#areaFill)" />
      <path :d="series.line" fill="none" stroke="#d9541e" stroke-width="2.2" stroke-linecap="round" />
      <g v-for="p in series.pts" :key="p.round">
        <circle v-if="p.event" :cx="p.x" :cy="p.y" r="7" fill="none" stroke="#e2b95d" stroke-opacity="0.45" />
        <circle :cx="p.x" :cy="p.y" :r="p.event ? 4 : 3" :fill="p.event ? '#e2b95d' : '#d9541e'" />
      </g>
      <text :x="series.first.x" :y="H - 7" fill="#5f7268" font-size="9" text-anchor="middle">R{{ series.first.round }}</text>
      <text :x="series.last.x" :y="H - 7" fill="#5f7268" font-size="9" text-anchor="middle">R{{ series.last.round }}</text>
      <circle :cx="series.last.x" :cy="series.last.y" r="8" fill="none" stroke="#d9541e" stroke-opacity="0.4">
        <animate attributeName="r" values="6;11;6" dur="2s" repeatCount="indefinite" />
        <animate attributeName="stroke-opacity" values="0.5;0;0.5" dur="2s" repeatCount="indefinite" />
      </circle>
    </svg>
    <div v-else class="evo-empty">方案获批后，过火面积将随轮次压制在此逐轮收敛；金色打点为触发重规划的轮次。</div>
  </div>
</template>
