<script setup>
// 火情监测·趋势分析条（2026-09-23 设计稿参考图）：五联图
// 图像时间序列 / 过火面积 / FLP 变化 / 人员状态 / 风速变化。
// 数据口径：面积出自 visual_sequence.frames（逐帧检测），FLP 与风速出自轮次账本
// （before/after），人员状态出自轮次记录——无数据时如实显示空态，不编造曲线。
import { computed } from 'vue'

const props = defineProps({
  frames: { type: Array, default: () => [] }, // [{url,label,time}]
  visualSequence: { type: Object, default: null },
  rounds: { type: Array, default: () => [] },
  peopleStatus: { type: String, default: 'unknown' },
  windNow: { type: [Number, String], default: null },
  fireAreaNow: { type: [Number, String], default: null },
})

const PEOPLE_META = {
  confirmed: { label: '有人', cls: 'people-confirmed' },
  absent: { label: '无人', cls: 'people-absent' },
  unknown: { label: '不确定', cls: 'people-unknown' },
}

// ---------- 迷你折线几何（各面板共用） ----------
const CW = 240
const CH = 96
const CPAD = { l: 30, r: 10, t: 12, b: 16 }

function buildSeries(values) {
  const clean = values.map((v) => Number(v)).filter((v) => Number.isFinite(v))
  if (clean.length < 2) return null
  const max = Math.max(...clean, 1)
  const step = (CW - CPAD.l - CPAD.r) / (clean.length - 1)
  const yOf = (v) => CH - CPAD.b - (v / max) * (CH - CPAD.t - CPAD.b)
  const pts = clean.map((v, i) => ({ x: CPAD.l + i * step, y: yOf(v), v }))
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
  return { pts, line, max, area: `${line} L${pts.at(-1).x.toFixed(1)},${CH - CPAD.b} L${pts[0].x.toFixed(1)},${CH - CPAD.b} Z` }
}
const fmt = (n) => (Math.abs(n) >= 1000 ? (n / 1000).toFixed(1) + 'k' : Number(n) >= 100 ? Math.round(n) : n.toFixed(1))

// 面板2 · 过火面积：visual_sequence.frames 逐帧 fire_area_m2（或 trend.areas_m2 兜底）
const areaSeries = computed(() => {
  const seq = props.visualSequence
  if (!seq) return null
  const frames = Array.isArray(seq.frames) && seq.frames.length ? seq.frames : []
  const values = frames.map((f) => Number(f.fire_area_m2)).filter((v) => Number.isFinite(v))
  const alt = !values.length && Array.isArray(seq.trend?.areas_m2) ? seq.trend.areas_m2.map(Number) : values
  const series = buildSeries(alt)
  if (!series) return null
  return { ...series, unit: 'm²', last: series.pts.at(-1).v, count: alt.length }
})

// 面板3 · FLP：轮次 after 值（当前）+ 逐轮累计自然增长（无压制反事实线：首点取首轮 before，此后逐轮累加 growth）
const flpSeries = computed(() => {
  const rounds = props.rounds
  if (rounds.length < 2) return null
  const actual = []
  const counter = []
  for (const round of rounds) {
    const after = Number(round.after?.fire_load_flp ?? round.after?.flp)
    const before = Number(round.before?.fire_load_flp ?? round.before?.flp)
    const growth = Number(round.after?.flp_ledger?.growth_flp) || Number(round.before?.flp_ledger?.growth_flp) || 0
    if (!Number.isFinite(after)) continue
    counter.push(counter.length ? counter.at(-1) + growth : (Number.isFinite(before) ? before : after))
    actual.push(after)
  }
  const s1 = buildSeries(actual)
  if (!s1) return null
  const max = Math.max(...actual, ...counter, 1)
  const rescale = (values, ref) => {
    const step = (CW - CPAD.l - CPAD.r) / (values.length - 1)
    return values.map((v, i) => ({ x: CPAD.l + i * step, y: CH - CPAD.b - (v / ref) * (CH - CPAD.t - CPAD.b), v }))
  }
  const aPts = rescale(actual, max)
  const cPts = rescale(counter, max)
  const path = (pts) => pts.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
  return {
    max, count: actual.length, last: actual.at(-1),
    line: path(aPts), area: `${path(aPts)} L${aPts.at(-1).x.toFixed(1)},${CH - CPAD.b} L${aPts[0].x.toFixed(1)},${CH - CPAD.b} Z`,
    counterLine: path(cPts), counterLast: counter.at(-1),
    firstLabel: `R1`, lastLabel: `R${rounds.length}`,
  }
})

// 面板4 · 人员状态：轮次 people_status 分段带（含研判前当前值）
const peopleBand = computed(() => {
  const seq = []
  const initial = { status: props.peopleStatus, round: '研判' }
  const items = [initial, ...props.rounds.map((round, i) => ({ status: round.after?.people_status ?? round.before?.people_status ?? 'unknown', round: `R${i + 1}` }))]
  for (const item of items) {
    const meta = PEOPLE_META[item.status] || PEOPLE_META.unknown
    if (seq.length && seq.at(-1).status === item.status) { seq.at(-1).rounds.push(item.round); continue }
    seq.push({ status: item.status, label: meta.label, cls: meta.cls, rounds: [item.round] })
  }
  return seq
})
const peopleCurrent = computed(() => PEOPLE_META[props.peopleStatus] || PEOPLE_META.unknown)

// 面板5 · 风速：轮次观测 + 当前环境风速为起点
const windSeries = computed(() => {
  const values = []
  if (props.windNow != null && props.windNow !== '') values.push(Number(props.windNow))
  for (const round of props.rounds) {
    const v = Number(round.after?.wind_speed ?? round.before?.wind_speed)
    if (Number.isFinite(v)) values.push(v)
  }
  const series = buildSeries(values)
  if (!series) return null
  return { ...series, unit: 'm/s', last: series.pts.at(-1).v, count: values.length }
})

function yTicks(max) {
  return [0, 0.5, 1].map((f) => ({ y: CH - CPAD.b - f * (CH - CPAD.t - CPAD.b), label: fmt(max * f) }))
}
const xFirst = CPAD.l
const xLast = CW - CPAD.r
</script>

<template>
  <div class="fm-trend-strip" role="region" aria-label="趋势分析">
    <!-- 1 图像时间序列 -->
    <div class="fm-trend-panel">
      <div class="fm-tp-head"><b>图像时间序列</b><span>{{ frames.length ? `${frames.length} 帧` : '暂无序列' }}</span></div>
      <div v-if="frames.length" class="fm-tp-thumbs">
        <div class="fm-tt-rail">
          <button v-for="(frame, i) in frames" :key="frame.url + i" :class="['fm-tt-cell', { active: i === frames.length - 1 }]" :title="frame.label">
            <img :src="frame.url" :alt="frame.label">
          </button>
        </div>
        <div class="fm-tt-axis">
          <span v-for="(frame, i) in frames" :key="'t' + i" :class="{ active: i === frames.length - 1 }">{{ frame.time || `帧${i + 1}` }}</span>
        </div>
      </div>
      <div v-else class="fm-tp-empty">多选图片或上传视频<br>逐帧时间序列在此显示</div>
    </div>

    <!-- 2 过火面积趋势 -->
    <div class="fm-trend-panel">
      <div class="fm-tp-head"><b>过火面积趋势</b><span class="fm-tp-unit">m²</span></div>
      <svg v-if="areaSeries" class="fm-tp-svg" :viewBox="`0 0 ${CW} ${CH}`" preserveAspectRatio="none" role="img" aria-label="过火面积逐帧变化">
        <defs>
          <linearGradient id="fmAreaFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#ff9f43" stop-opacity="0.30" />
            <stop offset="100%" stop-color="#ff9f43" stop-opacity="0.02" />
          </linearGradient>
        </defs>
        <g v-for="tick in yTicks(areaSeries.max)" :key="tick.label + tick.y">
          <line :x1="xFirst" :x2="xLast" :y1="tick.y" :y2="tick.y" stroke="#16345e" :stroke-dasharray="tick.label === '0.0' ? '' : '3 5'" />
          <text :x="4" :y="tick.y + 3" fill="#7e9abf" font-size="9">{{ tick.label }}</text>
        </g>
        <path :d="areaSeries.area" fill="url(#fmAreaFill)" />
        <path :d="areaSeries.line" fill="none" stroke="#ff9f43" stroke-width="2" stroke-linecap="round" />
        <circle :cx="areaSeries.pts.at(-1).x" :cy="areaSeries.pts.at(-1).y" r="3" fill="#ff9f43" />
        <text :x="xFirst" :y="CH - 4" fill="#7e9abf" font-size="9">帧1</text>
        <text :x="xLast" :y="CH - 4" fill="#7e9abf" font-size="9" text-anchor="end">帧{{ areaSeries.count }}</text>
      </svg>
      <div v-else class="fm-tp-empty">接入 ≥2 帧影像序列后<br>显示逐帧过火面积变化</div>
      <span v-if="areaSeries" class="fm-tp-last">最新 <b>{{ Math.round(areaSeries.last) }}</b> m²</span>
    </div>

    <!-- 3 FLP 变化趋势 -->
    <div class="fm-trend-panel">
      <div class="fm-tp-head"><b>FLP 变化趋势</b><span class="fm-tp-legend"><i class="solid"></i>当前 FLP <i class="dash"></i>自然增长</span></div>
      <svg v-if="flpSeries" class="fm-tp-svg" :viewBox="`0 0 ${CW} ${CH}`" preserveAspectRatio="none" role="img" aria-label="火情负荷逐轮变化">
        <defs>
          <linearGradient id="fmFlpFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#ff9f43" stop-opacity="0.26" />
            <stop offset="100%" stop-color="#ff9f43" stop-opacity="0.02" />
          </linearGradient>
        </defs>
        <g v-for="tick in yTicks(flpSeries.max)" :key="tick.label + tick.y">
          <line :x1="xFirst" :x2="xLast" :y1="tick.y" :y2="tick.y" stroke="#16345e" :stroke-dasharray="tick.label === '0.0' ? '' : '3 5'" />
          <text :x="4" :y="tick.y + 3" fill="#7e9abf" font-size="9">{{ tick.label }}</text>
        </g>
        <path :d="flpSeries.area" fill="url(#fmFlpFill)" />
        <path :d="flpSeries.line" fill="none" stroke="#ff9f43" stroke-width="2" stroke-linecap="round" />
        <path :d="flpSeries.counterLine" fill="none" stroke="#3d8bff" stroke-width="1.6" stroke-dasharray="5 4" />
        <text :x="xFirst" :y="CH - 4" fill="#7e9abf" font-size="9">{{ flpSeries.firstLabel }}</text>
        <text :x="xLast" :y="CH - 4" fill="#7e9abf" font-size="9" text-anchor="end">{{ flpSeries.lastLabel }}</text>
      </svg>
      <div v-else class="fm-tp-empty">批准方案进入轮次推演后<br>显示逐轮 FLP 变化</div>
      <span v-if="flpSeries" class="fm-tp-last">第 {{ flpSeries.count }} 轮 <b>{{ flpSeries.last.toFixed(1) }}</b> FLP</span>
    </div>

    <!-- 4 人员状态变化 -->
    <div class="fm-trend-panel">
      <div class="fm-tp-head"><b>人员状态变化</b><span class="fm-tp-legend"><i class="sw people-confirmed"></i>有人 <i class="sw people-absent"></i>无人 <i class="sw people-unknown"></i>不确定</span></div>
      <div class="fm-people-band" role="img" aria-label="人员状态逐轮变化">
        <span v-for="(seg, i) in peopleBand" :key="i" :class="seg.cls" :title="`${seg.rounds.join('、')} · ${seg.label}`">{{ seg.label }}</span>
      </div>
      <span class="fm-tp-last">当前 <b :class="peopleCurrent.cls">{{ peopleCurrent.label }}</b></span>
      <p class="fm-people-note">有人时启用疏散分支与避让 · 状态变化触发重规划</p>
    </div>

    <!-- 5 风速变化 -->
    <div class="fm-trend-panel">
      <div class="fm-tp-head"><b>风速变化</b><span class="fm-tp-unit">m/s</span></div>
      <svg v-if="windSeries" class="fm-tp-svg" :viewBox="`0 0 ${CW} ${CH}`" preserveAspectRatio="none" role="img" aria-label="风速逐轮变化">
        <defs>
          <linearGradient id="fmWindFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#3d8bff" stop-opacity="0.28" />
            <stop offset="100%" stop-color="#3d8bff" stop-opacity="0.02" />
          </linearGradient>
        </defs>
        <g v-for="tick in yTicks(windSeries.max)" :key="tick.label + tick.y">
          <line :x1="xFirst" :x2="xLast" :y1="tick.y" :y2="tick.y" stroke="#16345e" :stroke-dasharray="tick.label === '0.0' ? '' : '3 5'" />
          <text :x="4" :y="tick.y + 3" fill="#7e9abf" font-size="9">{{ tick.label }}</text>
        </g>
        <path :d="windSeries.area" fill="url(#fmWindFill)" />
        <path :d="windSeries.line" fill="none" stroke="#3d8bff" stroke-width="2" stroke-linecap="round" />
        <circle :cx="windSeries.pts.at(-1).x" :cy="windSeries.pts.at(-1).y" r="3" fill="#3d8bff" />
        <text :x="xFirst" :y="CH - 4" fill="#7e9abf" font-size="9">起点</text>
        <text :x="xLast" :y="CH - 4" fill="#7e9abf" font-size="9" text-anchor="end">最新</text>
      </svg>
      <div v-else class="fm-tp-empty">环境风速与轮次观测<br>到位后显示变化曲线</div>
      <span v-if="windSeries" class="fm-tp-last">最新 <b>{{ windSeries.last.toFixed(1) }}</b> m/s</span>
    </div>
  </div>
</template>
