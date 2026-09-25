<script setup>
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import TacticalMap from './components/TacticalMap.vue'
import ChatPanel from './components/ChatPanel.vue'
import ReportViewer from './components/ReportViewer.vue'
import ReplayPanel from './components/ReplayPanel.vue'
import ComparePanel from './components/ComparePanel.vue'
import HistoryPanel from './components/HistoryPanel.vue'
import UploadPanel from './components/UploadPanel.vue'
import DecisionPanel from './components/DecisionPanel.vue'
import MonitorVideoStage from './components/MonitorVideoStage.vue'
import TrendStrip from './components/TrendStrip.vue'
const Terrain3D = defineAsyncComponent(() => import('./components/Terrain3D.vue'))
import EvolutionChart from './components/EvolutionChart.vue'
import AreaTrendChart from './components/AreaTrendChart.vue'
import {
  LAYER_LABELS,
  SUBGROUP_COLORS,
  VLM_ERROR_LABELS,
  ZIXIAHU_BASE_GPS,
  statusLabels,
} from './constants'
import {
  agentMsgLabel,
  roadClass,
  agentSourceLabel,
  formatNumber,
  issueText,
  logText,
  logTime,
  moduleLabel,
  replanTriggerLabel,
  waterTypeClass,
  waterTypeLabel,
} from './utils/labels'
import { useLogs } from './composables/useLogs'
import { useEnvironment } from './composables/useEnvironment'
import { useVoice } from './composables/useVoice'
import { useMissionClock } from './composables/useMissionClock'
import { useWeather, refreshWeather } from './composables/useWeather'
import {
  Activity,
  BarChart3,
  BatteryCharging,
  Bell,
  Bot,
  Boxes,
  ChevronRight,
  ClipboardList,
  Cloud,
  CloudFog,
  CloudLightning,
  CloudRain,
  CloudSnow,
  CloudSun,
  Crosshair,
  Database,
  Droplets,
  ExternalLink,
  FileDown,
  FileText,
  Flame,
  Home,
  LayoutDashboard,
  ListFilter,
  MapPinned,
  MonitorUp,
  Plane,
  Play,
  Radio,
  RefreshCw,
  Settings,
  Sun,
  Target,
  Wind,
  Zap,
} from 'lucide-vue-next'

const activeTab = ref('map') // 用户拍板：默认落地态势总览（大屏）；研判流程经 E2E harness 统一导航适配
const analyzing = ref(false)
const monitoring = ref(false)
const uploaded = ref(false)
const selectedFile = ref(null)
const previewUrl = ref('')
const progress = ref(0)
const errorMessage = ref('')
const analysisEnvelope = ref(null)
const analysisResult = ref(null)
const analysisId = ref('')
const fleet = ref([])
const inventory = ref(null)
const peopleStatus = ref('unknown')
const useVlm = ref(false)
const maxDrones = ref(4)
const targetMinutes = ref(null)
const disabledUavs = ref([])
// BE-13（评审问题1 · 2+6+4 扩容接通）+ BE-18（机群扩至 12 架）：全机群 R1-R2 + E1-E6 + S1-S4 共 12 架，
// 其中可灭火机 = 灭火单元 E1-E6 + multi_role 支援机 S3/S4（8 架）。出动上限选项与禁用名单全部从 /api/fleet
// 动态生成，不再写死；机群接口不可用时回退 4 选项演示口径。
const fightingUavIds = computed(() => drones.value.filter((d) => d.role === 'firefighting' || d.multi_role).map((d) => d.id))
const maxDronesOptions = computed(() => Math.max(fightingUavIds.value.length, 4))
const disableOptions = computed(() => (fightingUavIds.value.length ? fightingUavIds.value : ['E1', 'E2', 'E3', 'E4']))
const reasonInput = ref('')
const reportViewer = ref({ open: false })
const expandedFleet = ref(new Set())
function toggleFleetDetail(id) {
  const next = new Set(expandedFleet.value)
  next.has(id) ? next.delete(id) : next.add(id)
  expandedFleet.value = next
}

// —— 可交互效果（FE-11）：图层开关 / 标记详情卡 / 面板↔地图联动 ——
const layerVisibility = ref({ fire: true, water: true, road: true, drone: true, contour: true, evacuation: true })
function toggleLayer(key) {
  layerVisibility.value = { ...layerVisibility.value, [key]: !layerVisibility.value[key] }
  addLog(`图层 ${LAYER_LABELS[key]} ${layerVisibility.value[key] ? '已显示' : '已隐藏'}`)
}
const activeMarker = ref(null)
const hoveredDroneId = ref('')
const hoveredWaterId = ref('')
function selectMarker(marker) {
  if (!marker || activeMarker.value?.id === marker.id) { activeMarker.value = null; return }
  const leftPct = parseFloat(marker.x) || 50
  const rows = []
  let title = marker.label
  if (marker.type === 'drone') {
    const drone = drones.value.find((d) => d.id === marker.id)
    title = marker.id
    rows.push(
      { k: '角色', v: drone?.label || '—' },
      { k: '状态', v: drone?.status || '—' },
      { k: 'SOC', v: `${drone?.soc ?? '—'}%` },
      { k: '模块', v: moduleLabel(drone?.module) },
      { k: '当前任务', v: drone?.task || '待命' },
    )
  } else if (marker.type === 'water') {
    const water = waterSourcesList.value.find((w) => w.id === marker.id)
    title = `${water?.preferred ? '★ ' : ''}${water?.name || '水源'}`
    rows.push(
      { k: '类型', v: water?.type || '—' },
      { k: '距离', v: water?.distance != null ? `${water.distance}m` : '—' },
      ...(water?.coordinates ? [{ k: '坐标', v: `${water.coordinates.longitude.toFixed(6)}°E, ${water.coordinates.latitude.toFixed(6)}°N` }] : []),
      ...(water?.preferred ? [{ k: '调度', v: '首选补水目标' }] : []),
    )
  } else if (marker.type === 'fire') {
    const fire = analysisResult.value?.fire_assessment || {}
    title = '火点中心'
    rows.push(
      { k: '火情等级', v: fire.label || '—' },
      { k: '火情负荷', v: fire.fire_load_flp != null ? `${fire.fire_load_flp} FLP` : '—' },
      { k: '面积', v: fire.fire_area_m2 != null ? `${formatNumber(fire.fire_area_m2)} m²` : '—' },
      { k: '增长率', v: fire.growth_rate != null ? `${fire.growth_rate}/h` : '—' },
      { k: '坐标', v: fireGpsLabel.value },
    )
  } else if (marker.type === 'road') {
    title = '最近道路'
  }
  activeMarker.value = {
    id: marker.id, title, rows,
    style: { left: marker.x, top: marker.y, transform: `translate(${leftPct > 62 ? 'calc(-100% - 14px)' : '14px'}, -50%)` },
  }
}
const focusPulse = ref('')

// —— 真实卫星地图（高德）：Key 缺失或加载失败时回退等高线示意图 ——
const tacticalMapRef = ref(null)
const amapRuntimeFailed = ref(false)
const cursorCoords = ref(null)
// 选点模式（模拟发现火情）：开启后在地图点击即把火点坐标指到该处
const pickMode = ref(false)
const amapReady = computed(() => Boolean(import.meta.env.VITE_AMAP_KEY) && !amapRuntimeFailed.value)
function onAmapFallback(reason) {
  if (amapRuntimeFailed.value) return
  amapRuntimeFailed.value = true
  addLog(`高德地图不可用（${reason}），已回退等高线示意图`)
}
function onWaterRowClick(water) {
  if (!water.position) return
  if (amapReady.value && tacticalMapRef.value) { tacticalMapRef.value.focusMarker(water.id); return }
  selectMarker({ id: water.id, type: 'water', x: water.position.x, y: water.position.y })
}
function dismissMarker(event) {
  // 高德覆盖物 / 详情卡 / 图例自身的点击不关闭详情；点击底图空白处关闭
  if (event.target?.closest?.('.amap-marker, .marker-detail, .map-legend, .map-controls, .map-node')) return
  activeMarker.value = null
}
const selectedFrames = ref([])
const streamedTaskId = ref('')
const approvalBusy = ref(false)
const contourData = ref(null)
const contourLoading = ref(false)
const contourRequestToken = ref(0)
const mapZoom = ref(1)
const mapPan = ref({ x: 0, y: 0 })
const mapDragging = ref(false)
const mapDragStart = ref({ x: 0, y: 0 })
const stages = ref([])
const eventsRequestToken = ref(0)
const historyTasks = ref([])
const historyLoading = ref(false)
const taskStatus = ref('待命')
const currentStage = ref('等待影像接入')
const agentMessages = ref([])
const llmInfo = ref(null)
const monitorResult = ref(null)
const rounds = ref([])
const serviceOnline = ref(false)
const projectStatus = ref({ framework: 'checking', demo_pipeline: 'checking', yolo: 'pending', vlm: 'pending', geo_data: 'demo-data' })
const { logs, foldedLogs, addLog } = useLogs([
  { timestamp: '', stage: 'system', source: 'local', message: '系统已连接 · 等待新的侦察数据' },
  { timestamp: '', stage: 'scene', source: 'local', message: '场景「紫金山演示林区」已载入' },
  { timestamp: '', stage: 'fleet', source: 'local', message: '无人机集群状态同步完成' },
])

const scene = {
  id: 'forest-demo-01',
  name: '紫金山侦察区',
  incident: '北坡火情 · 初始研判',
  coordinates: '118.8432°E · 32.0688°N',
  windSpeed: 6.5,
  windDirection: '西北',
  altitude: 320,
  terrain: '丘陵',
  waterDistance: 800,
}

const {
  environment,
  environmentLoading,
  environmentMode,
  environmentCoordinates,
  coordinateDraft,
  coordinateError,
  environmentAgeText,
  environmentStatus,
  environmentSource,
  environmentStale,
  environmentFallback,
  environmentLocation,
  environmentFeatures,
  applyCoordinates,
  loadEnvironment,
} = useEnvironment({ sceneId: scene.id, addLog, onCoordinateApplied: () => loadContours() })

const drones = ref([
  { id: 'R1', label: '侦察单元', role: 'reconnaissance', subgroup: 'reconnaissance', battery: 92, soc: 92, status: '待命', module: 'EO/IR', payload: '—', signal: 96, health: 100, color: 'blue', task: '待命' },
  { id: 'R2', label: '侦察单元', role: 'reconnaissance', subgroup: 'reconnaissance', battery: 88, soc: 88, status: '待命', module: 'EO/IR', payload: '—', signal: 94, health: 98, color: 'blue', task: '待命' },
  { id: 'E1', label: '灭火单元', role: 'firefighting', subgroup: 'suppression', battery: 92, soc: 92, status: '待命', module: 'water_20l', payload: '20 L', signal: 90, health: 100, color: 'orange', task: '待命' },
  { id: 'E2', label: '灭火单元', role: 'firefighting', subgroup: 'suppression', battery: 86, soc: 86, status: '待命', module: 'water_20l', payload: '20 L', signal: 88, health: 100, color: 'orange', task: '待命' },
  { id: 'E3', label: '灭火单元', role: 'firefighting', subgroup: 'suppression', battery: 79, soc: 79, status: '待命', module: 'co2_6kg', payload: '6 kg', signal: 86, health: 97, color: 'orange', task: '待命' },
  { id: 'E4', label: '灭火单元', role: 'firefighting', subgroup: 'suppression', battery: 74, soc: 74, status: '待命', module: 'water_20l', payload: '20 L', signal: 84, health: 96, color: 'orange', task: '待命' },
  { id: 'E5', label: '灭火单元', role: 'firefighting', subgroup: 'suppression', battery: 90, soc: 90, status: '待命', module: 'water_20l', payload: '20 L', signal: 91, health: 100, color: 'orange', task: '待命' },
  { id: 'E6', label: '灭火单元', role: 'firefighting', subgroup: 'suppression', battery: 84, soc: 84, status: '待命', module: 'water_20l', payload: '20 L', signal: 87, health: 98, color: 'orange', task: '待命' },
  { id: 'S1', label: '支援单元', role: 'support', subgroup: 'support', battery: 95, soc: 95, status: '待命', module: 'sup_10', payload: '10 kg', signal: 98, health: 100, color: 'green', task: '待命' },
  { id: 'S2', label: '支援单元', role: 'support', subgroup: 'support', battery: 90, soc: 90, status: '待命', module: 'sup_10', payload: '10 kg', signal: 95, health: 99, color: 'green', task: '待命' },
  { id: 'S3', label: '支援单元 · 多用途', role: 'support', subgroup: 'support', battery: 93, soc: 93, status: '待命', module: 'water_20l', payload: '20 L', signal: 96, health: 100, color: 'green', task: '待命' },
  { id: 'S4', label: '支援单元 · 多用途', role: 'support', subgroup: 'support', battery: 88, soc: 88, status: '待命', module: 'water_20l', payload: '20 L', signal: 93, health: 99, color: 'green', task: '待命' },
])

const FLEET_GROUP_META = [
  { key: 'reconnaissance', label: '侦察单元', role: '火情侦察与态势回传' },
  { key: 'suppression', label: '灭火单元', role: '主力灭火 · W20 水剂 / C6 二氧化碳模块' },
  { key: 'support', label: '支援单元', role: '物资补给与中继保障' },
]
const fleetGroups = computed(() => FLEET_GROUP_META
  .map((meta) => ({ ...meta, drones: drones.value.filter((drone) => drone.subgroup === meta.key) }))
  .filter((group) => group.drones.length))

// 本地演示兜底结果仅在后端不可用时展示；字段与 docs/api-contract.md §7 对齐，
// 使用 2+6+4 口径（2026-09-08 扩编）和仿真时间区间，不出现旧三机/单点分钟结论。
const fallbackResult = {
  analysis_id: 'analysis-demo-001',
  fire_assessment: { level: 2, label: 'II 级 · 中等火情', fire_area_m2: 1800, smoke_area_m2: 4200, confidence: 0.91, spread_direction: '西北', fire_load_flp: 245.7, growth_rate: 0.42 },
  environment: { wind_speed: 6.5, wind_direction: '西北', altitude: 320, terrain: '丘陵', nearest_water_distance_m: 800 },
  dispatch_plan: {
    schema_version: 'uav-dispatch-v1',
    plan_id: 'plan-demo00001',
    plan_version: 1,
    can_control: true,
    feasibility: true,
    required_drones: 2,
    selected_uavs: ['R1', 'E1', 'E2', 'S1'],
    recommended_material: 'water',
    material_module: 'water_20l',
    material_amount: 80,
    fire_load_flp: 245.7,
    effective_flp: 92.4,
    people_branch: 'unknown',
    resource_gap: [],
    alternative_plan: [],
    replan_trigger: ['fire_load_increase_over_20_percent', 'wind_band_changed', 'soc_below_return_threshold'],
    estimated_control_time: { earliest_minutes: 12, latest_minutes: 17, window_minutes: [12, 17], unit: 'min', simulated: true },
    estimated_minutes: null,
    tasks: [
      { drone_id: 'R1', task: '持续侦察', branch: 'reconnaissance' },
      { drone_id: 'E1', task: '主力灭火', module: 'water_20l', target_flp: 122.85 },
      { drone_id: 'E2', task: '主力灭火', module: 'water_20l', target_flp: 122.85 },
      { drone_id: 'S1', task: '复核人员与后备侦察', branch: 'support' },
    ],
  },
  explanation: '当前为 II 级 · 中等火情，火情负荷约 245.7 FLP（18 个 100m² 网格），西北风可能推动火势向西北扩散。R1 持续监测，E1/E2 主力灭火，S1 复核人员；时间为仿真区间，后端服务恢复后以实时研判为准。',
  data_mode: '本地演示数据 · 规则引擎',
}

const result = computed(() => {
  const base = analysisResult.value || fallbackResult
  if (!environment.value) return base
  return { ...base, environment: { ...base.environment, ...environment.value } }
})
const displayStatus = computed(() => statusLabels[analysisEnvelope.value?.status] || analysisEnvelope.value?.status || taskStatus.value)
const plan = computed(() => result.value.dispatch_plan || {})
const resourceGap = computed(() => plan.value.resource_gap || result.value.resource_gap || [])
// 契约字段为 earliest_minutes/latest_minutes/window_minutes（api-contract.md §7），旧 min/max 仅兜底。
const controlWindow = computed(() => {
  const time = plan.value.estimated_control_time || {}
  const start = time.earliest_minutes ?? time.min ?? time.window_minutes?.[0]
  const end = time.latest_minutes ?? time.max ?? time.window_minutes?.[1]
  if (start == null && end == null) return '—'
  return `${start ?? '—'}–${end ?? '—'} 分钟`
})
// plan_id/plan_version 的唯一来源是 envelope.plan_versions（result.dispatch_plan 不含这两个字段）
const currentPlanVersion = computed(() => analysisEnvelope.value?.plan_versions?.at(-1) || {})
const planVersionLabel = computed(() => {
  const version = plan.value.plan_version ?? currentPlanVersion.value.plan_version
  return version ? `v${version}` : ''
})
const currentPlanId = computed(() => plan.value.plan_id || currentPlanVersion.value.plan_id || '')
const peopleRisk = computed(() => peopleStatus.value === 'unknown' ? '人员情况不确定：禁止低空近距离作业，需先确认现场是否有人。' : peopleStatus.value === 'confirmed' ? '有人风险：已启用人员避让与人工复核，禁止自动投放。' : '已确认无人：仍需保持通信与撤离通道。')
const activeRounds = computed(() => rounds.value.length ? rounds.value : (analysisEnvelope.value?.rounds || []))
const monitorArea = computed(() => monitorResult.value?.next_fire_area_m2 ?? result.value.fire_assessment.fire_area_m2)
// FE-70 火情态势块：等级/趋势/判读全部出自既有字段（fire_assessment + 最新轮 flp_ledger）
const fireFlpNow = computed(() => {
  const latest = activeRounds.value.at(-1)?.after?.fire_load_flp
  return latest ?? plan.value.fire_load_flp ?? result.value.fire_assessment?.fire_load_flp ?? null
})
const fireLedger = computed(() => activeRounds.value.at(-1)?.after?.flp_ledger || null)
const fireTrend = computed(() => fireLedger.value?.net_change_flp ?? null)
const fireLevelNum = computed(() => {
  const raw = Number(result.value.fire_assessment?.level)
  return raw >= 1 && raw <= 4 ? raw : 1
})
const fireLevelWord = computed(() => ({ 1: '轻度火情', 2: '中度火情', 3: '重度火情', 4: '极度火情' })[fireLevelNum.value])
const fireTrendText = computed(() => {
  if (!fireLedger.value) return null
  const net = Number(fireLedger.value.net_change_flp)
  return {
    down: net < 0,
    text: net < 0 ? '压制见效 · 火势下降中' : '增长超过压制 · 火势扩大中',
    detail: `压制 ${formatNumber(fireLedger.value.suppression_flp)} / 增长 ${formatNumber(fireLedger.value.growth_flp)} FLP 每轮`,
  }
})
const dataMode = computed(() => result.value.data_mode || '本地演示数据 · 规则引擎')
// VLM 视觉解释（E-2 开发侧就绪）：vlm_explanation 由后端三级来源生成（vlm 直连 / 适配器 / 规则回退），来源随行标注
const frameTrendText = computed(() => {
  const seq = result.value && result.value.visual_sequence
  if (!seq || (seq.frame_count || 0) < 2) return ''
  const trend = seq.trend || {}
  const label = trend.trend === 'growing' ? '火势扩散' : trend.trend === 'shrinking' ? '火势减退' : trend.trend === 'stable' ? '火势持平' : (trend.trend || '未知')
  const parts = [`帧序列 ${seq.frame_count} 帧`, `面积趋势 ${label}`, `面积变化 ${trend.area_delta_m2 != null ? trend.area_delta_m2 : '—'} m²`]
  if (trend.center_delta_m != null) parts.push(`火点位移 ${trend.center_delta_m} m`)
  return parts.join(' · ')
})
const inputProvenanceText = computed(() => {
  const prov = result.value && result.value.input_provenance
  if (!prov || !prov.image_sha256_16) return ''
  const frames = (prov.frame_sha256_16 || []).length
  return `输入溯源 · ${prov.image_name || '未命名'} · sha256:${prov.image_sha256_16}` + (frames ? ` · 序列帧 ×${frames}` : '')
})
const vlmNote = computed(() => result.value.vlm_explanation || null)
const vlmNoteBody = computed(() => {
  const note = vlmNote.value
  if (!note) return ''
  return note.human_summary || note.summary || ''
})
// OPT-P3-01：三态结论视图——can_control 布尔升级为 can_control/maintain_only/cannot_control，
// 文案与 reason_code 同源（后端 _control_decision），R2/R9 关键词（启动/增援/暂不可控）保持兼容
const controlVerdictView = computed(() => {
  const plan = result.value?.dispatch_plan || {}
  const verdict = plan.control_verdict || (plan.can_control ? 'can_control' : 'cannot_control')
  const reason = plan.control_reason_code || ''
  if (verdict === 'can_control') {
    return { tone: 'ok', hero: '可控制 · 建议立即出动', callout: '建议立即启动一级处置响应', hint: '可控', report: '可控制 · 处置方案成立' }
  }
  if (verdict === 'maintain_only') {
    const detail = reason === 'time_limit_exceeded' ? '时限内未完成' : '慢压维持'
    return {
      tone: 'mid', hero: `维持压制 · ${detail}`,
      callout: reason === 'time_limit_exceeded' ? '压得住但超出时限 · 建议增援或放宽时限' : '慢压维持中 · 建议增援加快处置',
      hint: '维持压制', report: '维持压制 · 时限/仿真窗口内未完成',
    }
  }
  return { tone: 'bad', hero: '暂不可控 · 请求增援', callout: '压制不足 · 建议立即请求增援', hint: '超出能力，建议增援', report: '暂不可控 · 已输出资源缺口' }
})
// OPT-P1-01：失败原因按后端错误码准确归因——只有 429 才说限流，超时/鉴权/响应异常各说各话
const vlmNoteSource = computed(() => {
  const note = vlmNote.value
  if (!note) return ''
  const statusLabel = { real: '真实识别', fallback: '规则回退', skipped: '未调用', error: '失败' }
  const bits = [note.mode === 'real' ? (note.source || 'vlm') : (note.source || 'rule-explainer-fallback')]
  if (note.status && statusLabel[note.status]) bits.push(statusLabel[note.status])
  if (note.prompt_version) bits.push(`提示词 ${note.prompt_version}`)
  if (note.adapter_fallback?.code) bits.push(`回退 ${note.adapter_fallback.code}`)
  const errCode = note.adapter_fallback?.error_code
  if (errCode && VLM_ERROR_LABELS[errCode]) bits.push(VLM_ERROR_LABELS[errCode])
  else if (['vlm_call_failed', 'vlm_endpoint_unavailable'].includes(note.adapter_fallback?.code || '')) {
    bits.push('调用失败，稍后重传可获真实识别')
  }
  if (note.degraded_reason) bits.push(`VLM 不可用(${note.degraded_reason})`)
  return bits.join(' · ')
})
const vlmNoteIssues = computed(() => {
  const note = vlmNote.value || {}
  const guard = (note.contract_guard || {}).violations || []
  return [...(note.conflicts || []), ...(note.anomalies || []), ...guard].map(issueText).filter(Boolean)
})
const vlmNoteFacts = computed(() => {
  const note = vlmNote.value || {}
  const facts = []
  if (note.usable === false) facts.push(`图像不可用${Array.isArray(note.missing_inputs) && note.missing_inputs.length ? ' · 缺 ' + note.missing_inputs.join('、') : ''}`)
  else if (note.quality_level) facts.push(`图像质量 ${note.quality_level}`)
  const peopleState = note.people?.state
  if (peopleState) facts.push(`人员 ${peopleState === 'not_observed' ? '未观察到' : peopleState === 'observed' ? '有线索' : peopleState}`)
  if (note.smoke_density) facts.push(`烟雾 ${typeof note.smoke_density === 'string' ? note.smoke_density : note.smoke_density.level || ''}`)
  if (note.visual_scale) facts.push(`视觉规模 ${typeof note.visual_scale === 'string' ? note.visual_scale : note.visual_scale.level || ''}`)
  const trend = note.temporal_trend
  if (trend) facts.push(`时序 ${typeof trend === 'string' ? trend : trend.trend || trend.direction || ''}`)
  if (note.manual_review_required) facts.push('需人工复核')
  return facts.filter(Boolean)
})
// 有人分支疏散路线（规则 V1 §9）：confirmed 时核心链输出 evacuation
const evacuationSummary = computed(() => {
  const eva = analysisResult.value?.agent?.skill_chain?.evacuation
  if (!eva?.found) return ''
  return `模拟路径（演示网格 BFS）· 路线 ${eva.steps} 步 · 约 ${eva.estimated_minutes} 分钟 · 避开 ${eva.risk_cells} 个风险格`
})
// —— 疏散语音广播（FE-21，范式参考 firepatrol TTS）：有人分支路线生成即口播，可一键静音 ——
const { voiceOn, toggleVoice, speakText } = useVoice({ addLog })
const spokenEvacFor = ref('')
watch(() => analysisResult.value && analysisResult.value.agent && analysisResult.value.agent.skill_chain
  ? analysisResult.value.agent.skill_chain.evacuation : null, (eva) => {
  if (!voiceOn.value || !eva || !eva.found || !analysisId.value || spokenEvacFor.value === analysisId.value) return
  spokenEvacFor.value = analysisId.value
  speakText(`人员区域请注意:现场发现火情,请立即沿疏散路线向出口撤离,全程约 ${eva.estimated_minutes} 分钟,共 ${eva.steps} 段路线,避开 ${eva.risk_cells} 个风险格,救援无人机将在上空引导。`)
})

// 火势环比已并入火情监测「火情量化」面板（净变化 FLP 行）
// FE-74 英雄决策条已随页面设计（2026-09）拆入火情监测「识别/量化」面板与机群调度「调度结论」

// 页面设计（2026-09-23 设计稿）：一级导航冻结为六页；Agent 协作收进机群调度「决策过程」，
// 系统设置取消一级页面（投影→顶栏 / 模型状态→火情监测 / 服务状态→左下角 / 环境模式→火情监测），
// 文案保持 e2e 契约不变（harness 依赖「火情监测」导航与 .upload-panel）
const navItems = [
  { id: 'map', label: '态势总览', icon: Home },
  { id: 'command', label: '火情监测', icon: Flame },
  { id: 'dispatch', label: '机群调度', icon: Plane },
  { id: 'history', label: '任务管理', icon: ClipboardList },
  { id: 'fleet', label: '资源管理', icon: Boxes },
  { id: 'analysis', label: '数据分析', icon: BarChart3 },
]

const mapProjection = computed(() => {
  const origin = pointCoordinates(environmentLocation.value) || environmentCoordinates.value
  const points = [origin, ...(environment.value?.water_sources || []), environment.value?.nearest_water, environment.value?.road_context?.nearest_transport, environment.value?.road_context?.nearest_vehicle_access_candidate]
    .map(pointCoordinates)
    .filter(Boolean)
  const meters = (point) => {
    const coordinates = pointCoordinates(point) || origin
    const lat = Number(coordinates.latitude); const lon = Number(coordinates.longitude)
    const latScale = 111320; const lonScale = 111320 * Math.cos(Number(origin.latitude) * Math.PI / 180)
    return { x: (lon - Number(origin.longitude)) * lonScale, y: (lat - Number(origin.latitude)) * latScale }
  }
  const projected = points.map(meters)
  const extent = Math.max(500, ...projected.map((p) => Math.hypot(p.x, p.y)))
  return { origin, meters, extent }
})
function pointCoordinates(point) {
  const position = point?.position || {}
  const latitude = Number(point?.latitude ?? position.latitude)
  const longitude = Number(point?.longitude ?? position.longitude)
  return Number.isFinite(latitude) && Number.isFinite(longitude) ? { latitude, longitude } : null
}

function relativePoint(point) {
  const position = point?.position || point || {}
  const x = Number(position.x); const y = Number(position.y)
  return Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null
}

function markerPosition(point) {
  const coordinates = pointCoordinates(point)
  const relative = relativePoint(point)
  if (!coordinates && !relative) return null
  const p = coordinates ? mapProjection.value.meters(coordinates) : relative
  const extent = mapProjection.value.extent
  return { x: `${Math.max(5, Math.min(95, 50 + (p.x / extent) * 42))}%`, y: `${Math.max(5, Math.min(95, 50 - (p.y / extent) * 42))}%` }
}

// 火点位置由任务数据驱动：优先结果内的相对坐标火点（与机群同系），否则回退地图中心。
const firePosition = computed(() => markerPosition(analysisResult.value?.scene?.fire_origin || null) || { x: '50%', y: '50%' })
const fireGpsLabel = computed(() => {
  const gps = analysisResult.value?.scene?.fire_origin_gps
  return gps ? `${Number(gps.longitude).toFixed(6)}°E · ${Number(gps.latitude).toFixed(6)}°N` : (scene.coordinates || '')
})
// 水源清单：按距离排序，标注类型与首选水源（preferred_water 优先级：水库/湖泊/池塘）
const waterSourcesList = computed(() => {
  const waters = Array.isArray(environment.value?.water_sources) ? environment.value.water_sources : []
  const preferred = environment.value?.preferred_water
  return waters
    .map((water, index) => ({
      id: `water-${water.id || water.name || "x"}-${index}`,
      name: water.name || '未命名水体',
      type: waterTypeLabel(water),
      distance: Number.isFinite(Number(water.distance_m)) ? Math.round(Number(water.distance_m)) : null,
      coordinates: pointCoordinates(water),
      position: markerPosition(water),
      preferred: Boolean(preferred && (water.name === preferred.name || (water.latitude === preferred.latitude && water.longitude === preferred.longitude))),
      verified: water.verification_status === 'verified',
      safety: water.safety_status == null ? null : Boolean(water.safety_status),
      capacity: water.capacity_liters != null && Number.isFinite(Number(water.capacity_liters)) ? Number(water.capacity_liters) : null,
    }))
    .sort((a, b) => (a.distance ?? Infinity) - (b.distance ?? Infinity))
})
const mapMarkers = computed(() => {
  const taskByDrone = {}
  for (const task of (analysisResult.value?.dispatch_plan?.tasks || [])) taskByDrone[task.drone_id] = task.task
  const road = environment.value?.road_context?.nearest_transport || environment.value?.road_context?.nearest_vehicle_access_candidate
  const markers = []
  if (layerVisibility.value.fire) {
    markers.push({ id: 'fire', type: 'fire', label: `火点中心 · ${fireGpsLabel.value}`, icon: Flame, ...firePosition.value })
  }
  if (layerVisibility.value.water) {
    for (const water of waterSourcesList.value) {
      if (!water.position) continue
      markers.push({ id: water.id, type: 'water', waterType: water.type, preferred: water.preferred,
        label: `${water.preferred ? '首选 · ' : ''}${water.name} · ${water.type}${water.distance != null ? ` · ${water.distance}m` : ''}`, icon: Droplets, ...water.position })
    }
  }
  const roadPosition = markerPosition(road)
  if (layerVisibility.value.road && road && roadPosition) {
    markers.push({ id: 'road', type: 'road', label: `${road.name || '最近道路'} · ${road.distance_m ?? '—'}m`, icon: MapPinned, ...roadPosition })
  }
  if (layerVisibility.value.drone) {
    drones.value.forEach((drone, index) => {
      // 环形部署布局：相对坐标在大范围等高线视图下过密，改为以火点为中心均匀环绕（战术图惯例）
      // 椭圆环适配宽幅地图：x 半径大于 y 半径，保证 8 个标记两两分离
      const angle = (index / Math.max(drones.value.length, 1)) * Math.PI * 2 - Math.PI / 2
      const ringX = mapProjection.value.extent * 0.30
      const ringY = mapProjection.value.extent * 0.18
      const center = analysisResult.value?.scene?.fire_origin || { x: 140, y: 60 }
      const position = relativeToPercent({ x: center.x + Math.cos(angle) * ringX, y: center.y + Math.sin(angle) * ringY })
      // 战术图惯例：地图上只显示编号，SOC/任务详情在悬停提示与部署面板
      const title = `${drone.id} ${drone.label} · SOC ${drone.soc ?? '—'}% · ${drone.status} · ${taskByDrone?.[drone.id] || drone.task || '待命'}`
      markers.push({ id: drone.id, type: 'drone', label: drone.id, title, icon: Radio, soc: drone.soc, sub: drone.subgroup, ...position })
    })
  }
  return markers
})
// 米制比例尺：markerPosition 以 ±extent 米映射到 ±42% 宽度，据此换算整刻度长度。
const mapScale = computed(() => {
  const extent = mapProjection.value.extent
  const target = extent / 3
  const nice = [100, 200, 250, 500, 1000, 2000, 5000].find((value) => value >= target) || 10000
  return { width: `${Math.min(56, (nice / extent) * 84).toFixed(1)}%`, label: nice >= 1000 ? `${nice / 1000} km` : `${nice} m` }
})

// 相对坐标(米) → 地图百分比（与 markerPosition 同一投影）
function relativeToPercent(point) {
  const extent = mapProjection.value.extent
  return {
    x: `${Math.max(4, Math.min(96, 50 + (point.x / extent) * 42))}%`,
    y: `${Math.max(4, Math.min(96, 50 - (point.y / extent) * 42))}%`,
  }
}

// 迷你四旋翼 SOC 环的 stroke-dasharray（r=15.5 周长 97.39，FE-20）
function quadDash(soc) {
  const c = 2 * Math.PI * 15.5
  const v = Math.max(0, Math.min(100, Number(soc) || 0))
  return `${((v / 100) * c).toFixed(1)} ${c.toFixed(1)}`
}

// 火情范围圈：fire_area_m2 等效圆半径，随轮次监测收缩（参考战术地图火格显示）
const fireZone = computed(() => {
  const area = Number(analysisResult.value?.fire_assessment?.fire_area_m2)
  const origin = analysisResult.value?.scene?.fire_origin
  if (!area || area <= 0 || !origin) return null
  const extent = mapProjection.value.extent
  const radius = Math.sqrt(area / Math.PI)
  const percent = Math.max(4, Math.min(80, ((radius * 2) / extent) * 84))
  return { ...relativeToPercent(origin), size: `${percent.toFixed(1)}%` }
})

// 疏散路线叠加：evacuation 路径网格 → 以火点为原点的相对坐标折线（网格 12x12/40m，中心=火点）
const evacuationOverlay = computed(() => {
  const eva = analysisResult.value?.agent?.skill_chain?.evacuation
  const origin = analysisResult.value?.scene?.fire_origin
  if (!eva?.found || !eva.path?.length || !origin) return null
  const points = eva.path.map(([c, r]) => relativeToPercent({ x: origin.x + (c - 6) * 40, y: origin.y + (r - 6) * 40 }))
  return { points: points.map((p) => `${p.x.replace('%', '')},${p.y.replace('%', '')}`).join(' '), exit: points[points.length - 1], minutes: eva.estimated_minutes }
})

// 任务部署面板数据：每架 UAV 的状态/SOC/当前任务（来自 dispatch tasks）
const deploymentList = computed(() => {
  const tasks = analysisResult.value?.dispatch_plan?.tasks || []
  const taskByDrone = {}
  for (const task of tasks) taskByDrone[task.drone_id] = task.task
  return drones.value.map((drone) => ({
    id: drone.id,
    label: drone.label,
    soc: Number(drone.soc ?? 0),
    status: drone.status,
    task: taskByDrone[drone.id] || drone.assigned_task || drone.task || '待命',
    selected: (analysisResult.value?.dispatch_plan?.selected_uavs || []).includes(drone.id),
    subgroup: drone.subgroup || '',
  }))
})

// —— 指挥大屏（FE-19）KPI 已随页面设计（2026-09）并入右栏「任务执行/环境与趋势」卡 ——
const replanCount = computed(() => Math.max(0, (analysisEnvelope.value?.plan_versions?.length || 1) - 1))

const terrainVisual = computed(() => {
  const terrain = environment.value?.terrain || {}
  const elevation = Number(terrain.elevation_m ?? environment.value?.altitude ?? scene.altitude)
  const slope = Number(terrain.slope_deg ?? 8)
  return {
    elevation: Number.isFinite(elevation) ? Math.round(elevation) : scene.altitude,
    slope: Number.isFinite(slope) ? slope.toFixed(1) : '—',
    upslope: terrain.upslope_direction || '北',
    downslope: terrain.downslope_direction || '南',
    contourStep: Math.max(10, Math.round(Math.abs(slope) * 2)),
  }
})
// FE-72 SVG 回退图统一投影：等高线与真实路网共用同一 extent（联合范围），避免两套比例错位
const svgRoads = computed(() => {
  const roads = environment.value?.road_context?.roads
  if (!Array.isArray(roads)) return []
  // 等高线足印约 0.07°（≈7.8km），道路取 3km 足印内更贴近画面中心
  return roads.filter((road) => Number(road.distance_m) <= 3000).slice(0, 40)
})
const svgGeometry = computed(() => {
  const features = contourData.value?.features
  const contourCoordinates = Array.isArray(features) && features.length
    ? features.flatMap((feature) => {
        const geometry = feature?.geometry
        if (geometry?.type === 'LineString') return [geometry.coordinates]
        if (geometry?.type === 'MultiLineString') return geometry.coordinates || []
        return []
      }).filter((line) => line.length >= 2)
    : []
  const project = ({ latitude, longitude }) => mapProjection.value.meters({ latitude, longitude })
  const contourMeters = contourCoordinates.map((line) => line.map(([longitude, latitude]) => project({ latitude, longitude })))
  const roadMeters = svgRoads.value.map((road) => (road.geometry || []).map(([longitude, latitude]) => project({ latitude, longitude })))
  const points = [...contourMeters.flat(), ...roadMeters.flat()]
  const extent = points.length ? Math.max(500, ...points.map((point) => Math.hypot(point.x, point.y))) : 0
  return { contourMeters, roadMeters, extent, hasContours: contourCoordinates.length > 0 }
})
const svgRoadPaths = computed(() => {
  const { roadMeters, extent } = svgGeometry.value
  if (!extent || !roadMeters.length) return []
  return svgRoads.value.map((road, index) => {
    const line = roadMeters[index]
    if (!line || line.length < 2) return null
    const points = line.map(({ x, y }) => `${(500 + (x / extent) * 450).toFixed(1)} ${(260 - (y / extent) * 235).toFixed(1)}`)
    return { wayId: road.way_id, d: `M ${points.join(' L ')}`, cls: roadClass(road.highway) }
  }).filter(Boolean)
})

const contourPaths = computed(() => {
  const { contourMeters, extent, hasContours } = svgGeometry.value
  if (hasContours && contourMeters.length) {
    const features = contourData.value.features
    return contourMeters.map((line, index) => {
      const points = line.map(({ x, y }) => `${(500 + (x / extent) * 450).toFixed(1)} ${(260 - (y / extent) * 235).toFixed(1)}`)
      const feature = features[index]
      const elevation = Number(feature?.properties?.elevation_m ?? feature?.properties?.elevation ?? '')
      return { d: `M ${points.join(' L ')}`, elevation: Number.isFinite(elevation) ? Math.round(elevation) : null, major: index % 4 === 0, labelX: 500 + (line[0].x / extent) * 450, labelY: 260 - (line[0].y / extent) * 235 }
    })
  }
  const slope = Number(environment.value?.terrain?.slope_deg ?? 8)
  const elevation = Number(environment.value?.terrain?.elevation_m ?? environment.value?.altitude ?? scene.altitude)
  const stretch = Math.max(0.72, Math.min(1.25, 0.9 + slope / 45))
  const peakX = 560
  const peakY = 248
  const levels = 9
  return Array.from({ length: levels }, (_, index) => {
    const radius = 38 + index * 38
    const wobble = 1 + (elevation % 17) / 180
    const points = Array.from({ length: 28 }, (_, pointIndex) => {
      const angle = (pointIndex / 28) * Math.PI * 2
      const harmonic = 1 + 0.07 * Math.sin(angle * 3 + index * 0.8) + 0.035 * Math.cos(angle * 5 - index)
      const x = peakX + Math.cos(angle) * radius * stretch * harmonic
      const y = peakY + Math.sin(angle) * radius * wobble * harmonic
      return `${x.toFixed(1)} ${y.toFixed(1)}`
    })
    return {
      d: `M ${points.join(' L ')} Z`,
      elevation: Math.round(elevation + (levels - 1 - index) * terrainVisual.value.contourStep),
      labelX: peakX + radius * stretch * 0.68,
      labelY: peakY - radius * 0.2,
      major: index === 0 || index === 3 || index === 6,
    }
  })
})

// 地图选点（模拟发现火情）：把点击处的 WGS-84 坐标指为火点，走与环境面板相同的应用链
function applyPickedCoords(picked) {
  coordinateDraft.value = { latitude: Number(picked.latitude.toFixed(6)), longitude: Number(picked.longitude.toFixed(6)) }
  pickMode.value = false
  applyCoordinates()
}

watch(environmentCoordinates, (coords) => refreshWeather(coords))

async function loadContours() {
  const requestToken = ++contourRequestToken.value
  contourLoading.value = true
  try {
    const { latitude, longitude } = environmentCoordinates.value
    const query = new URLSearchParams({ latitude: String(latitude), longitude: String(longitude), radius_deg: '0.07', interval_m: '20', max_points: '240' })
    const response = await fetch(`/api/terrain/contours?${query}`)
    if (!response.ok) throw new Error('等高线接口不可用')
    const payload = await response.json()
    if (requestToken !== contourRequestToken.value) return
    if (!Array.isArray(payload?.features) || !payload.features.length) throw new Error('等高线数据为空')
    contourData.value = payload
    addLog(`等高线已加载 · ${payload.source || '真实数据'}`)
  } catch (error) {
    if (requestToken === contourRequestToken.value) {
      contourData.value = null
      addLog('等高线加载失败 · 使用合成等高线')
    }
    console.warn(error)
  } finally {
    if (requestToken === contourRequestToken.value) contourLoading.value = false
  }
}

function zoomMap(delta) {
  mapZoom.value = Math.max(0.6, Math.min(3, Number((mapZoom.value + delta).toFixed(2))))
}
function resetMapView() { mapZoom.value = 1; mapPan.value = { x: 0, y: 0 } }
function startMapDrag(event) {
  if (event.button !== 0) return
  // 交互元素（标记/图例/面板/控件）不触发地图拖拽，避免 pointer capture 吞掉点击
  if (event.target?.closest?.('.map-node, .map-legend, .map-controls, .water-panel, .deploy-panel, .map-source, .marker-detail, .stream-panel, .map-taskbar')) return
  mapDragging.value = true
  event.currentTarget?.setPointerCapture?.(event.pointerId)
  mapDragStart.value = { x: event.clientX - mapPan.value.x, y: event.clientY - mapPan.value.y }
}
function moveMap(event) {
  if (!mapDragging.value) return
  mapPan.value = { x: event.clientX - mapDragStart.value.x, y: event.clientY - mapDragStart.value.y }
}
function stopMapDrag() { mapDragging.value = false }
function handleMapWheel(event) {
  event.preventDefault()
  zoomMap(event.deltaY < 0 ? 0.1 : -0.1)
}
const mapLayerStyle = computed(() => ({ transform: `translate3d(${mapPan.value.x}px, ${mapPan.value.y}px, 0) scale(${mapZoom.value})` }))

const canRetryAnalysis = computed(() => Boolean(errorMessage.value && errorMessage.value.includes('研判')))


function selectNav(id) {
  activeTab.value = id
  if (id === 'history' || id === 'analysis') loadHistory()
}

// —— 顶栏：高德实时天气 + 本地时钟（FE-80，对齐设计稿顶栏；天气为背景信息不参与计算） ——
const { weather } = useWeather()
const weatherIcon = computed(() => {
  const text = weather.value?.text || ''
  if (text.includes('雷')) return CloudLightning
  if (text.includes('雨')) return CloudRain
  if (text.includes('雪')) return CloudSnow
  if (text.includes('雾') || text.includes('霾')) return CloudFog
  if (text.includes('晴') && text.includes('云')) return CloudSun
  if (text.includes('晴')) return Sun
  return Cloud
})
const weatherTitle = computed(() => {
  const w = weather.value
  if (!w) return ''
  return `高德实时天气 · ${w.district || '当前区域'} · 发布 ${w.reportTime || '—'}（背景信息，不参与火情计算）`
})
const wallDate = ref('')
const wallTime = ref('')
let wallTimer = null
function tickWallClock() {
  const now = new Date()
  wallDate.value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  wallTime.value = now.toLocaleTimeString('zh-CN', { hour12: false })
}

async function selectHistoryTask(task) {
  if (!task?.analysis_id) return
  // 列表走 slim 摘要（不含 result），点击时按需拉取完整信封再恢复。
  let full = task
  if (!task.result) {
    try {
      const detail = await fetch(`/api/analyze/${task.analysis_id}`)
      if (!detail.ok) throw new Error('任务详情获取失败')
      full = await detail.json()
    } catch (error) {
      errorMessage.value = '历史任务详情暂不可用。'
      console.warn(error)
      return
    }
  }
  applyEnvelope(full)
  monitorResult.value = full.result?.monitor || null
  // 阶段对象字段为 {id,label,status,source}（审计 P1）：优先 label，兼容旧 stage/name
  const lastStage = full.stages?.at(-1)
  currentStage.value = lastStage?.label || lastStage?.stage || lastStage?.name || '历史任务已恢复'
  if (Array.isArray(full.stages)) stages.value = full.stages
  if (Array.isArray(full.result?.fleet)) updateDrones(full.result)
  loadEvents(task.analysis_id)
  activeTab.value = 'command'
}

function updateDrones(payload) {
  if (!Array.isArray(payload?.fleet)) return
  drones.value = payload.fleet.map((drone, index) => {
    const id = drone.id || drone.uav_id || `UAV-${index + 1}`
    const role = drone.role || (drone.subgroup === 'suppression' ? 'firefighting' : drone.subgroup || 'support')
    const status = statusLabels[drone.status] || drone.status || '待命'
    return { ...drone, id, uav_id: drone.uav_id || id, subgroup: drone.subgroup || role, role, battery: Number(drone.battery ?? drone.soc ?? 0), soc: Number(drone.soc ?? drone.battery ?? 0), signal: Number(drone.signal ?? drone.signal_strength ?? 0), health: Number(drone.health ?? 0), module: drone.module || drone.payload_module || '—', payload: drone.payload || drone.agent_remaining || '—', status, label: drone.label || (role === 'reconnaissance' ? '侦察单元' : role === 'firefighting' ? '灭火单元' : '支援单元'), color: drone.color || (role === 'reconnaissance' ? 'blue' : role === 'firefighting' ? 'orange' : 'green'), task: payload.dispatch_plan?.tasks?.find((task) => task.drone_id === id)?.task || drone.assigned_task || '待命' }
  })
}

async function loadFleetAndInventory() {
  try {
    const [fleetResponse, inventoryResponse] = await Promise.all([fetch('/api/fleet'), fetch('/api/inventory')])
    if (fleetResponse.ok) {
      const payload = await fleetResponse.json()
      fleet.value = Array.isArray(payload?.fleet) ? payload.fleet : []
      updateDrones({ fleet: fleet.value })
      addLog(`集群状态已同步 · ${drones.value.length} 架无人机`)
    }
    if (inventoryResponse.ok) inventory.value = await inventoryResponse.json()
  } catch (error) { console.warn(error); addLog('集群/库存接口不可用 · 使用本地演示数据') }
}


// SSE 实时事件流（api-contract §5.10）：任务变更时订阅，事件实时上屏；终态 done 后自动关闭。
let eventStream = null
let streamedEventKeys = new Set()
function eventKey(event) {
  return `${event.timestamp}|${event.stage}|${event.message}`
}
function openEventStream(id) {
  closeEventStream()
  if (!id || !window.EventSource) return
  streamedTaskId.value = id
  streamedEventKeys = new Set()
  eventStream = new EventSource(`/api/tasks/${id}/events/stream`)
  eventStream.onmessage = (message) => {
    try {
      const event = JSON.parse(message.data)
      const key = eventKey(event)
      if (!event?.message || streamedEventKeys.has(key)) return
      streamedEventKeys.add(key)
      // 与 loadEvents 拉取路径去重：同一事件（时间戳+阶段+消息）只保留一条
      logs.value = [event, ...logs.value.filter((log) => log.timestamp !== event.timestamp || log.stage !== event.stage || log.message !== event.message)].slice(0, 200)
    } catch (error) { console.warn(error) }
  }
  eventStream.addEventListener('agent_message', (event) => {
    try {
      const message = JSON.parse(event.data)
      if (agentMessages.value.some((item) => item.seq === message.seq)) return
      agentMessages.value = [...agentMessages.value, message]
    } catch (error) { console.warn(error) }
  })
  loadAgentMessages(id)
  eventStream.addEventListener('done', () => closeEventStream())
}

async function loadAgentMessages(id) {
  if (!id) return
  try {
    const response = await fetch(`/api/tasks/${id}/agent-messages`)
    if (!response.ok) return
    const payload = await response.json()
    agentMessages.value = Array.isArray(payload.items) ? payload.items : []
  } catch (error) { console.warn(error) }
}
function closeEventStream() {
  if (eventStream) { eventStream.close(); eventStream = null }
  streamedTaskId.value = ''
}

function environmentForPayload() {
  // 研判上送当前环境坐标（紫金山主峰默认），与地图/环境面板保持一致。
  return environmentCoordinates.value
}

function adjustConstraints() {
  const constraints = { people_status: peopleStatus.value, max_drones: maxDrones.value }
  if (targetMinutes.value != null && Number(targetMinutes.value) > 0) constraints.target_minutes = Number(targetMinutes.value)
  if (disabledUavs.value.length) constraints.disabled_uavs = [...disabledUavs.value]
  return constraints
}

async function submitApproval(action, opts = {}) {
  if (!analysisId.value || approvalBusy.value) return
  // FE-45：林区态势任务条没有原因输入框，其终止按钮使用默认原因（此前被必填守卫
  // 静默拦截，按钮永远不可用）；研判页审批面板仍强制填写原因
  const reason = reasonInput.value.trim() || (opts.defaultReason || '')
  if ((action === 'reject' || action === 'terminate') && !reason) {
    errorMessage.value = '驳回或终止必须在原因框中说明原因。'
    return
  }
  approvalBusy.value = true
  if (action === 'terminate' || action === 'reject') stopAutoSim() // 先停自动推演，避免在途轮次与终止竞态
  try {
    const response = await fetch(`/api/tasks/${analysisId.value}/approval`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, plan_id: currentPlanId.value || null, constraints: adjustConstraints(), reason: reason || null }) })
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}))
      throw new Error(detail?.detail || `方案操作失败（${response.status}）`)
    }
    const payload = await response.json()
    if (action === 'adjust' && !payload.analysis_id) {
      // adjust 返回 plan 信封（api-contract §5.5），重新拉取任务完整状态
      const refreshed = await fetch(`/api/analyze/${analysisId.value}`)
      if (!refreshed.ok) throw new Error('调整成功但刷新任务状态失败')
      applyEnvelope(await refreshed.json())
    } else {
      applyEnvelope(payload)
      if (action === 'approve') startMission()
      if (action === 'terminate' || action === 'reject') stopMission()
    }
    reasonInput.value = ''
    addLog(`方案操作完成 · ${action}${reason ? ' · 原因：' + reason : ''}`)
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : '方案操作失败，请重试。'; console.warn(error) } finally { approvalBusy.value = false }
}

function applyEnvelope(payload) {
  const envelope = payload?.payload || payload
  analysisEnvelope.value = envelope
  analysisId.value = envelope?.analysis_id || ''
  analysisResult.value = envelope?.result || null
  stages.value = Array.isArray(envelope?.stages) ? envelope.stages : []
  taskStatus.value = statusLabels[envelope?.status] || envelope?.status || '待命'
  currentStage.value = stages.value.at(-1)?.label || stages.value.at(-1)?.stage || stages.value.at(-1)?.name || currentStage.value
  updateDrones(analysisResult.value)
  if (analysisResult.value?.environment) environment.value = analysisResult.value.environment
  if (envelope?.analysis_id && envelope.analysis_id !== streamedTaskId.value) openEventStream(envelope.analysis_id)
}

async function loadEvents(id = analysisId.value) {
  if (!id) return
  const requestToken = ++eventsRequestToken.value
  try {
    const response = await fetch(`/api/analyze/${id}/events`)
    if (!response.ok) throw new Error('事件接口不可用')
    const payload = await response.json()
    if (requestToken !== eventsRequestToken.value || id !== analysisId.value) return
    logs.value = Array.isArray(payload.events) ? payload.events : []
  } catch (error) {
    if (requestToken === eventsRequestToken.value) logs.value = []
    console.warn(error)
  }
}

async function loadHistory() {
  historyLoading.value = true
  try {
    const response = await fetch('/api/analyzes?limit=50&slim=1')
    if (!response.ok) throw new Error('历史任务接口不可用')
    historyTasks.value = (await response.json()).items || []
  } catch (error) {
    historyTasks.value = []
    addLog('历史任务暂不可用 · 保持当前本地状态')
    console.warn(error)
  } finally {
    historyLoading.value = false
  }
}

// 问答面板可用性：GLM available 与否由 loadServiceStatus 拉取的 /api/llm-status 决定（FE-22）
const chatEnabled = computed(() => Boolean(llmInfo.value && llmInfo.value.available))
// FE-63 告警中心：监测触发器/应急机/资源断供 → 右上告警堆栈（可关闭，上限 3 条）
const alarms = ref([])
// FE-71 指挥员口令：后端开启口令门时（FIREOPS_COMMANDER_TOKEN），401 触发输入条
const authRequired = ref(false)
const authTokenInput = ref('')
function onCommanderAuthRequired() { authRequired.value = true }
function saveCommanderToken() {
  const token = authTokenInput.value.trim()
  if (!token) return
  localStorage.setItem('commander-token', token)
  authRequired.value = false
  authTokenInput.value = ''
  addLog('指挥员口令已保存 · 请重新点击刚才的操作')
}
let alarmSeq = 0
watch(monitorResult, (m) => {
  if (!m) return
  const triggers = m.replan_triggers || []
  const emergency = m.emergency_units || []
  if (!triggers.length && !emergency.length) return
  alarmSeq += 1
  alarms.value.unshift({
    id: alarmSeq, time: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
    level: emergency.length ? 'bad' : 'warn',
    text: [triggers.join('、'), emergency.length ? `应急机 ${emergency.join('、')}` : ''].filter(Boolean).join(' · '),
  })
  if (alarms.value.length > 3) alarms.value.length = 3
})
function dismissAlarm(id) { alarms.value = alarms.value.filter((a) => a.id !== id) }
// FE-64 资源汇总：轮次消耗累计 + 期末库存 + 周转计数
const resourceSummary = computed(() => {
  let water = 0
  let co2 = 0
  for (const r of activeRounds.value) {
    const rc = (r.after || {}).resource_consumed || {}
    water += rc.water_liters || 0
    co2 += rc.co2_kg || 0
  }
  const fleetNow = result.value.fleet || []
  return {
    water: Math.round(water * 10) / 10,
    co2: Math.round(co2 * 100) / 100,
    swaps: fleetNow.reduce((s, d) => s + (d._swap_count || 0), 0),
    refills: fleetNow.reduce((s, d) => s + (d._refill_count || 0), 0),
  }
})
// —— UI-REDESIGN（2026-09 设计稿对齐）新增派生数据：全部出自既有状态，不引新口径 ——

// 机群编组表（机群调度页，设计稿「机群编组」三组表格）
const squadronTable = computed(() => fleetGroups.value.map((group) => ({
  key: group.key,
  label: group.label,
  cls: group.key === 'reconnaissance' ? 'gt-blue' : group.key === 'suppression' ? 'gt-orange' : 'gt-green',
  rows: group.drones.map((drone) => {
    const deploy = deploymentList.value.find((row) => row.id === drone.id)
    return {
      id: drone.id,
      task: deploy?.task || drone.task || '待命',
      soc: drone.soc,
      payload: moduleLabel(drone.module),
      status: drone.status,
      selected: Boolean(deploy?.selected),
    }
  }),
})))

// 资源总览 KPI（资源管理页，设计稿「资源总览」指标带）
const fleetStatusCounts = computed(() => {
  const total = drones.value.length
  const countStatus = (needle) => drones.value.filter((drone) => String(drone.status || '').includes(needle)).length
  const busy = drones.value.filter((drone) => ['执行中', '作业中', '飞行中', '已分配'].includes(drone.status)).length
  return {
    total,
    available: countStatus('待命'),
    busy,
    returning: countStatus('返航'),
    maintain: countStatus('维护') + countStatus('充电'),
    fault: countStatus('故障') + countStatus('离线'),
    water: waterSourcesList.value.length,
  }
})

// 物资库行（资源管理页，设计稿 2026-09-23 七列表格；库存出自 /api/inventory）。
// 「已占用」= 执行任务无人机随身携带的模块数（随机群状态实时变化）；
// 安全库存为演示口径阈值（inventory-v1 契约暂无该字段），低于即触发「需补充」预警。
const INVENTORY_SAFETY_STOCK = { w20: 6, c6: 2, battery: 16, supply: 2 }
const busyStatusSet = ['执行中', '作业中', '飞行中', '已分配']
const inventoryRows = computed(() => {
  const inv = inventory.value || {}
  const carried = (needle) => drones.value.filter((drone) => drone.module === needle && busyStatusSet.includes(drone.status)).length
  const rows = [
    { key: 'w20', name: 'W20 灭火剂水剂', unit: '模块', total: inv.water_modules_w20, occupied: carried('water_20l'), note: inv.water_liters != null ? `折合 ${inv.water_liters} L` : '' },
    { key: 'c6', name: 'C6 二氧化碳灭火弹', unit: '罐', total: inv.co2_modules_c6, occupied: carried('co2_6kg'), note: '设备/电气热点适用' },
    { key: 'battery', name: '备用电池', unit: '块', total: inv.battery_packs, occupied: drones.value.filter((drone) => ['维护中', '充电中'].includes(drone.status)).length, note: '换电周转' },
    { key: 'supply', name: '补给模块', unit: '套', total: inv.support_boxes_sup10, occupied: carried('sup_10'), note: '物资投送' },
  ]
  return rows.map((row) => {
    const total = row.total ?? null
    const available = Number.isFinite(total) ? Math.max(0, total - row.occupied) : null
    const low = Number.isFinite(available) && available < INVENTORY_SAFETY_STOCK[row.key]
    return { ...row, total: total ?? '—', available: available ?? '—', safety: INVENTORY_SAFETY_STOCK[row.key], low }
  })
})

// 无人机卡「剩余 W20 / 剩余 C6」（设计稿）：按载荷模块归属显示，非本类模块为 —
function droneAgentLeft(drone, kind) {
  const matched = kind === 'water' ? drone.module === 'water_20l' : drone.module === 'co2_6kg'
  if (!matched) return '—'
  const remaining = Number(drone.agent_remaining)
  if (Number.isFinite(remaining)) return `${remaining} ${drone.agent_unit || (kind === 'water' ? 'L' : 'kg')}`
  return drone.payload && drone.payload !== '—' ? String(drone.payload) : '—'
}

// 无人机卡「预计返航时间」（设计稿）：按当前 SOC 与耗电率估算续航钟点；非执行态显示 —
function droneEtaText(drone) {
  if (!busyStatusSet.includes(drone.status)) return '—'
  const soc = Number(drone.soc)
  const rate = Number(drone.energy_rate_percent_per_hour)
  if (!Number.isFinite(soc) || !Number.isFinite(rate) || rate <= 0) return '—'
  const eta = new Date(Date.now() + Math.max(1, Math.round((soc / rate) * 60)) * 60000)
  return `≈${String(eta.getHours()).padStart(2, '0')}:${String(eta.getMinutes()).padStart(2, '0')}`
}

// 前置驻防点（水源与驻防点表「所属驻防点」列）：取库存契约 forward_supply_points 首个可用点
const supplyBaseName = computed(() => (inventory.value?.forward_supply_points || []).find((point) => point.available)?.name || '—')

// 水源表「距离」列（设计稿以 km 计）：≥1 km 显示两位小数公里，不足保留米
function waterDistanceText(water) {
  if (water.distance == null) return '—'
  return water.distance >= 1000 ? `${(water.distance / 1000).toFixed(2)} km` : `${water.distance} m`
}

// 数据分析页：当前任务指标（设计稿「当前任务分析」四卡）
const anaStats = computed(() => {
  const rounds = activeRounds.value
  const ledger = fireLedger.value
  const first = rounds.length ? (rounds[0].before?.fire_load_flp ?? rounds[0].before?.flp) : null
  const last = rounds.length ? (rounds.at(-1).after?.fire_load_flp ?? rounds.at(-1).after?.flp) : null
  const changePct = (Number.isFinite(Number(first)) && Number.isFinite(Number(last)) && Number(first) > 0)
    ? ((Number(last) - Number(first)) / Number(first)) * 100
    : null
  const growth = ledger ? Number(ledger.growth_flp) : null
  const supp = ledger ? Number(ledger.suppression_flp) : null
  const eff = (growth != null && supp != null && growth + supp > 0) ? (supp / (growth + supp)) * 100 : null
  const units = (analysisResult.value?.dispatch_plan?.selected_uavs || []).length
  const socValues = drones.value.map((drone) => Number(drone.soc)).filter(Number.isFinite)
  const avgSoc = socValues.length ? socValues.reduce((sum, value) => sum + value, 0) / socValues.length : null
  return {
    changePct: changePct != null ? `${changePct > 0 ? '+' : ''}${changePct.toFixed(1)}%` : '—',
    changeDown: changePct != null && changePct < 0,
    growth: growth != null ? `+${formatNumber(growth)}` : '—',
    supp: supp != null ? `${formatNumber(supp)}` : '—',
    eff: eff != null ? `${eff.toFixed(1)}%` : '—',
    net: fireTrend.value != null ? `${fireTrend.value > 0 ? '+' : ''}${formatNumber(fireTrend.value)}` : '—',
    netDown: fireTrend.value != null && fireTrend.value < 0,
    rounds: rounds.length,
    replans: replanCount.value,
    units,
    water: resourceSummary.value.water,
    co2: resourceSummary.value.co2,
    swaps: resourceSummary.value.swaps,
    refills: resourceSummary.value.refills,
    avgSoc: avgSoc != null ? `-${Math.round(100 - avgSoc)}%` : '—',
  }
})

// 数据分析页：前后轮次对比表（设计稿「前后轮次对比」表格）
// 工作无人机 = 作业/飞行/已分配；返航 = returning；补给 = 充电/维护；库存变化 = W20/C6 模块与电池相对上一轮的增量
const roundsTable = computed(() => activeRounds.value.map((round, index) => {
  const after = round.after || {}
  const ledger = after.flp_ledger || null
  const action = round.next_action
  const fleet = Array.isArray(after.fleet) ? after.fleet : []
  const countBy = (predicate) => fleet.filter(predicate).length
  const consumed = after.resource_consumed || {}
  const invOf = (r) => (r?.after?.inventory || r?.after?.next_inventory) || null
  const inventoryNow = invOf(round)
  const inventoryPrev = index > 0 ? invOf(activeRounds.value[index - 1]) : null
  const stockParts = []
  if (inventoryNow) {
    const delta = (key) => (inventoryPrev ? Number(inventoryNow[key] ?? 0) - Number(inventoryPrev[key] ?? 0) : null)
    const w20 = delta('water_modules_w20')
    const c6 = delta('co2_modules_c6')
    const battery = delta('battery_packs')
    if (w20 != null && w20 !== 0) stockParts.push(`W20 ${w20 > 0 ? '+' : ''}${w20}`)
    if (c6 != null && c6 !== 0) stockParts.push(`C6 ${c6 > 0 ? '+' : ''}${c6}`)
    if (battery != null && battery !== 0) stockParts.push(`电池 ${battery > 0 ? '+' : ''}${battery}`)
    if (!stockParts.length && index > 0) stockParts.push('持平')
  }
  return {
    no: round.round || round.monitor_round || index + 1,
    before: round.before?.fire_load_flp ?? round.before?.flp ?? '—',
    after: after.fire_load_flp ?? after.flp ?? '—',
    growth: ledger?.growth_flp,
    supp: ledger?.suppression_flp,
    net: ledger?.net_change_flp,
    working: countBy((d) => ['working', 'flying', 'assigned'].includes(d.status)),
    returning: countBy((d) => d.status === 'returning'),
    supplying: countBy((d) => ['charging', 'servicing'].includes(d.status)),
    water: consumed.water_liters != null ? Number(consumed.water_liters) : null,
    co2: consumed.co2_kg != null ? Number(consumed.co2_kg) : null,
    stock: inventoryNow ? (stockParts.join(' · ') || '期初') : '—',
    action: action === 'awaiting_confirmation' ? '等待二次审批' : action === 'finish' ? '火情扑灭' : (action || '保持观察'),
    replan: Boolean((round.replan_triggers || round.replan_trigger || []).length),
  }
}))

// 数据分析页：多任务对比勾选（与任务管理页同一 ComparePanel 组件）
const anaCompareSel = ref([])
const anaCompareOpen = computed(() => anaCompareSel.value.length >= 2)
watch(anaCompareSel, (next) => {
  if (next.length > 4) anaCompareSel.value = next.slice(-4)
})

// 轮次与重规划信息条（机群调度页底部，设计稿「轮次与重规划」）
const socWarnList = computed(() => drones.value.filter((drone) => Number(drone.soc) < 30).map((drone) => `${drone.id} ${Math.round(drone.soc)}%`))
const faultList = computed(() => drones.value.filter((drone) => String(drone.status).includes('故障')).map((drone) => drone.id))
const latestReplanReason = computed(() => {
  const round = activeRounds.value.at(-1)
  const triggers = round?.replan_triggers || round?.replan_trigger || []
  if (triggers.length) return triggers.map(replanTriggerLabel).join('、')
  return monitorResult.value?.reason ? replanTriggerLabel(monitorResult.value.reason) : '无'
})
const planVersionsList = computed(() => (analysisEnvelope.value?.plan_versions || []).map((version) => ({
  id: version.plan_id || '',
  label: `V${version.plan_version}`,
  current: version.plan_version === currentPlanVersion.value.plan_version,
})))

// 态势总览右栏（设计稿「任务执行」环形进度卡）
const missionDonut = computed(() => {
  const total = drones.value.length || 12
  const active = (analysisResult.value?.dispatch_plan?.selected_uavs || []).length
  const c = 2 * Math.PI * 34
  return {
    active,
    total,
    dash: `${((active / Math.max(total, 1)) * c).toFixed(1)} ${c.toFixed(1)}`,
    pct: Math.round((active / Math.max(total, 1)) * 100),
  }
})
const subgroupCounts = computed(() => fleetGroups.value.map((group) => ({
  key: group.key,
  label: group.label.replace('单元', '机'),
  total: group.drones.length,
  active: group.drones.filter((drone) => deploymentList.value.find((row) => row.id === drone.id)?.selected).length,
})))
// 态势总览右栏（设计稿「环境与态势」卡）
const envPanelRows = computed(() => {
  const env = result.value.environment || {}
  const nearest = waterSourcesList.value[0]
  return [
    { label: '风速', value: env.wind_speed != null ? `${env.wind_speed} m/s` : '—' },
    { label: '风向', value: env.wind_direction ? `${env.wind_direction}风` : '—' },
    { label: '温度', value: weather.value ? `${weather.value.temperature} °C` : '—' },
    { label: '湿度', value: weather.value ? `${weather.value.humidity} %` : '—' },
    { label: '坡度', value: `${terrainVisual.value.slope} °` },
    { label: '最近水源', value: nearest ? `${nearest.name} ${nearest.distance != null ? nearest.distance + 'm' : ''}` : '—' },
  ]
})
const overviewStageLabel = computed(() => {
  if (mission.value?.active) return missionPhaseText('') || '推演作业中'
  return currentStage.value || displayStatus.value || '—'
})

// —— 页面设计（2026-09-23）火情监测页新派生数据：识别 / 量化 / 模型状态，全部出自既有口径 ——
// 视觉证据窗：原图 + 真实 YOLO 检测框（DecisionPanel 同款数据，火情监测页为画面主角）
const evidenceView = computed(() => {
  const data = analysisResult.value?.agent?.skill_chain?.fire_perception?.observation?.detector?.data || {}
  if (!previewUrl.value || data.mode !== 'real' || !Array.isArray(data.detections) || !data.detections.length) return null
  const width = Number(data.image_width) || 1920
  const height = Number(data.image_height) || 1080
  const boxes = data.detections.map((d) => {
    const [x1, y1, x2, y2] = d.box || [0, 0, 0, 0]
    return {
      cls: d.class_name === 'fire' ? '火焰' : d.class_name === 'smoke' ? '烟雾' : d.class_name,
      conf: Math.round((d.confidence || 0) * 100),
      left: `${(x1 / width) * 100}%`,
      top: `${(y1 / height) * 100}%`,
      width: `${((x2 - x1) / width) * 100}%`,
      height: `${((y2 - y1) / height) * 100}%`,
    }
  })
  return { image: previewUrl.value, boxes, model: data.model || 'yolo11n-dfire', fire: boxes.filter((b) => b.cls === '火焰').length, smoke: boxes.filter((b) => b.cls === '烟雾').length }
})
const evidenceShowBoxes = ref(true)

// 态势总览「实时画面」卡（设计稿参考图）：YOLO 识别摘要（最高置信度）+ 源机号
const liveFeedMeta = computed(() => {
  const view = evidenceView.value
  if (!view) return null
  const top = (cls) => view.boxes.filter((b) => b.cls === cls).reduce((max, b) => Math.max(max, b.conf), 0)
  return {
    fire: view.fire,
    smoke: view.smoke,
    fireConf: top('火焰'),
    smokeConf: top('烟雾'),
    uav: result.value.agent?.skill_chain?.fire_perception?.observation?.source_uav || 'R1',
  }
})

// 接入工具抽屉：无影像时默认展开（上传/演训是主入口），接入后自动收起让画面成为主角
const toolsOpen = ref(true)
function onToolsToggle(event) { toolsOpen.value = event.currentTarget.open }

// —— 影像主舞台（设计稿参考图）：帧序列缩略图管道 + 翻帧光标 + 来源信息 ——
// frameStrip = 早前帧 + 当前帧（末位）；早前帧 URL 由本组件创建并负责回收，previewUrl 归 App 生命周期
const frameStrip = ref([])
let ownedStripUrls = []
watch([selectedFrames, previewUrl], ([frames, mainUrl]) => {
  ownedStripUrls.forEach((url) => URL.revokeObjectURL(url))
  ownedStripUrls = frames.map((file) => URL.createObjectURL(file))
  const timeOf = (file) => file?.lastModified ? new Date(file.lastModified).toTimeString().slice(0, 5) : ''
  const items = frames.map((file, i) => ({ url: ownedStripUrls[i], label: file.name, time: timeOf(file) }))
  if (mainUrl) items.push({ url: mainUrl, label: selectedFile.value?.name || '当前帧', time: timeOf(selectedFile.value) })
  frameStrip.value = items
}, { immediate: true })
const activeFrameIndex = ref(0)
watch(() => frameStrip.value.length, (len) => { activeFrameIndex.value = Math.max(0, len - 1) })
watch(uploaded, (value) => { toolsOpen.value = !value })
onBeforeUnmount(() => ownedStripUrls.forEach((url) => URL.revokeObjectURL(url)))
// 舞台来源信息：拍摄时间（信封建档时间 > 文件时间）与画质（VLM 图片质量口径）
const stageCapturedAt = computed(() => {
  const stamp = analysisEnvelope.value?.created_at || ''
  if (stamp) return stamp.slice(11, 19)
  return selectedFile.value?.lastModified ? new Date(selectedFile.value.lastModified).toTimeString().slice(0, 8) : ''
})
const stageQuality = computed(() => {
  const quality = vlmNote.value?.image_quality
  if (!quality) return '良好'
  const level = quality.quality_level || quality.usable
  return level === true || level === 'good' ? '良好' : level === 'fair' || level === 'degraded' ? '一般' : level === false || level === 'poor' ? '差' : '良好'
})

// 模型状态简单标识（设计稿：YOLO 真实检测/回退；VLM 真实调用/回退/失败；模型名称；数据来源和时间）
const modelBadges = computed(() => {
  const note = vlmNote.value || {}
  const vlmState = note.mode === 'real'
    ? (note.status === 'error' ? '失败' : '真实调用')
    : (note.status === 'error' ? '失败' : note.mode === 'fallback' || note.mode === 'skipped' ? '规则回退' : '待调用')
  return [
    { name: 'YOLO', state: detectorStatus.value ? '真实检测' : '回退', detail: detectorStatus.value ? `${detectorStatus.value.model || 'yolo11n-dfire'} · ${detectorStatus.value.source || ''}` : '演示管线 · 规则映射', ok: Boolean(detectorStatus.value) },
    { name: 'VLM', state: vlmState, detail: note.model ? `${note.model}` : (vlmState === '真实调用' ? '视觉语言模型' : '未启用时由规则解释'), ok: vlmState === '真实调用' },
    { name: 'GLM 决策', state: llmInfo.value?.available ? '在线' : '离线降级', detail: llmInfo.value?.model || '确定性规则兜底', ok: Boolean(llmInfo.value?.available) },
  ]
})

// 火情识别结果行：只做视觉观察陈述，不夹带安全关键数值（数值归规则引擎）
const recognitionRows = computed(() => {
  const fire = result.value.fire_assessment || {}
  const note = vlmNote.value || {}
  const scaleOf = (value) => {
    const text = typeof value === 'string' ? value : (value?.level || value?.label || '')
    return text || '—'
  }
  return [
    { k: '火焰', v: fire.fire_area_m2 > 0 ? `存在 · 约 ${formatNumber(fire.fire_area_m2)} m²` : '未检出', tone: fire.fire_area_m2 > 0 ? 'bad' : 'ok' },
    { k: '烟雾', v: fire.smoke_area_m2 > 0 ? `存在 · 约 ${formatNumber(fire.smoke_area_m2)} m²` : '未检出', tone: fire.smoke_area_m2 > 0 ? 'warn' : 'ok' },
    { k: '视觉规模', v: scaleOf(note.visual_scale) },
    { k: '烟雾浓度', v: scaleOf(note.smoke_density) },
    { k: '火势趋势', v: frameTrendText.value ? frameTrendText.value.split(' · ').slice(1).join(' · ') || '见时间趋势' : (fireTrendText.value?.text || '待研判') },
    { k: '人员状态', v: { confirmed: '有人在场', absent: '无人员受威胁', unknown: '情况不明' }[peopleStatus.value] || '情况不明', tone: peopleStatus.value === 'confirmed' ? 'bad' : peopleStatus.value === 'unknown' ? 'warn' : 'ok' },
  ]
})

// 火情量化行：FLP 账本出自规则引擎（YOLO/VLM 只负责视觉观察）
const quantifyRows = computed(() => {
  const fire = result.value.fire_assessment || {}
  const ledger = fireLedger.value
  return [
    { k: '火情等级', v: fire.label || '—', tone: 'bad' },
    { k: '过火面积', v: fire.fire_area_m2 != null ? `${formatNumber(fire.fire_area_m2)} m²` : '—' },
    { k: '当前 FLP', v: fireFlpNow.value != null ? formatNumber(fireFlpNow.value) : '—' },
    { k: '自然增长 FLP', v: ledger ? `+${formatNumber(ledger.growth_flp)}` : '—', tone: 'bad' },
    { k: '有效压制 FLP', v: ledger ? formatNumber(ledger.suppression_flp) : '—', tone: 'ok' },
    { k: '净变化 FLP', v: fireTrend.value != null ? `${fireTrend.value > 0 ? '+' : ''}${formatNumber(fireTrend.value)}` : '—', tone: fireTrend.value != null && fireTrend.value < 0 ? 'ok' : fireTrend.value != null ? 'bad' : '' },
  ]
})

// 人员状态确认（设计稿「确认人员状态」按钮）：不确定 → 无人 → 有人 循环，按钮文案随当前值
const peopleCycleOrder = ['unknown', 'absent', 'confirmed']
function cyclePeopleStatus() {
  const index = peopleCycleOrder.indexOf(peopleStatus.value)
  peopleStatus.value = peopleCycleOrder[(index + 1) % peopleCycleOrder.length]
  addLog(`人员状态已确认为「${{ confirmed: '有人', absent: '无人', unknown: '不确定' }[peopleStatus.value]}」· 后续方案按此分支生成`)
}

// 生成调度方案（设计稿按钮）：无结果先研判，有结果直达机群调度
function gotoDispatchPlan() {
  if (!analysisResult.value && !scenario.value) { startAnalysis(); return }
  selectNav('dispatch')
}

// —— 机群调度「决策过程」折叠栏（原 Agent 协作一级页合并至此）——
const decisionFold = ref(false)

// 任务管理页详情（设计稿「任务管理」右侧详情栏；行点击=恢复主显示的契约不变，详情走独立按钮）
const historyDetail = ref(null)
const historyDetailLoading = ref(false)
async function openHistoryDetail(task) {
  if (!task?.analysis_id) return
  historyDetailLoading.value = true
  try {
    const response = await fetch(`/api/analyze/${task.analysis_id}`)
    if (!response.ok) throw new Error('详情获取失败')
    historyDetail.value = await response.json()
  } catch (error) {
    errorMessage.value = '任务详情暂不可用。'
    console.warn(error)
  } finally {
    historyDetailLoading.value = false
  }
}
const historyStages = computed(() => (historyDetail.value?.stages || []).map((stage, index) => ({
  no: index + 1,
  label: stage.label || stage.stage || stage.name || `阶段 ${index + 1}`,
  time: (stage.timestamp || stage.time || '').slice(11, 19) || '',
})))
const historyDetailRounds = computed(() => (historyDetail.value?.rounds || []).map((round, index) => ({
  no: round.round || round.monitor_round || index + 1,
  before: round.before?.fire_load_flp ?? '—',
  after: round.after?.fire_load_flp ?? round.after?.flp ?? '—',
  action: round.next_action || '—',
})))
// 数据分析页：设计稿「当前任务分析」——资源消耗五小卡 + 次级指标三卡
const anaResourceCards = computed(() => [
  { label: 'W20 消耗', value: `${anaStats.value.water}`, unit: 'L' },
  { label: 'C6 消耗', value: `${anaStats.value.co2}`, unit: 'kg' },
  { label: '出动架次', value: `${anaStats.value.units}`, unit: '架' },
  { label: '补水次数', value: `${anaStats.value.refills}`, unit: '次' },
  { label: '换电次数', value: `${anaStats.value.swaps}`, unit: '次' },
])
const anaSecondaryCards = computed(() => [
  { label: '重规划次数', value: `${anaStats.value.replans}`, unit: '次' },
  { label: '控制时间', value: controlWindow.value, unit: '预计区间' },
  { label: 'SOC 变化', value: anaStats.value.avgSoc, unit: '平均' },
])
// 状态彩签色调（资源卡/编组表共用）
function statusToneClass(status) {
  const value = String(status || '')
  if (value === '待命') return 'slate'
  if (['故障', '离线'].includes(value)) return 'red'
  if (['执行中', '作业中', '飞行中', '已分配'].includes(value)) return 'blue'
  if (['返航中', '维护中', '充电中'].includes(value)) return 'orange'
  return 'ok'
}
// 态势总览风向指示（设计稿地图右上风向标）：风向=来向，箭头指向风吹去的方向（+180°）
const windArrowDeg = computed(() => {
  const table = { 北: 0, 东北: 45, 东: 90, 东南: 135, 南: 180, 西南: 225, 西: 270, 西北: 315, N: 0, NE: 45, E: 90, SE: 135, S: 180, SW: 225, W: 270, NW: 315, ENE: 67.5, ESE: 112.5, SSW: 202.5, WSW: 247.5, NNE: 22.5, NNW: 337.5 }
  const from = table[result.value.environment?.wind_direction]
  return from == null ? null : from + 180
})
// —— 三维地形（FE-29）：高程网格懒加载 + 演示态势投影 ——
const mapMode = ref('2d')
const terrainGrid = ref(null)
const terrainGridLoading = ref(false)
const terrainGridKey = ref('')
async function loadTerrainGrid() {
  if (terrainGridLoading.value) return
  const { latitude, longitude } = environmentCoordinates.value
  // 地点键控缓存（OPT-P2-05）：同地点复用；地点变化清旧网格重载，防止沿用旧 3D 地形
  const key = `${latitude.toFixed(5)},${longitude.toFixed(5)}`
  if (terrainGrid.value && terrainGridKey.value === key) return
  terrainGridKey.value = key
  terrainGrid.value = null
  terrainGridLoading.value = true
  try {
    const query = new URLSearchParams({ latitude: String(latitude), longitude: String(longitude), radius_deg: '0.06', size: '161' })
    const response = await fetch(`/api/terrain/grid?${query}`)
    if (!response.ok) throw new Error(String(response.status))
    const payload = await response.json()
    if (payload.status === 'ok') terrainGrid.value = payload
  } catch (error) {
    addLog('三维地形网格加载失败 · 可稍后重试')
    console.warn(error)
  } finally { terrainGridLoading.value = false }
}
function toggleMapMode(mode) {
  mapMode.value = mode
  if (mode === '3d') loadTerrainGrid()
  addLog(`林区态势切换 ${mode === '3d' ? '三维模型' : '平面战术图'}`)
}
const fire3dGps = computed(() => fireGpsValue())
const fire3dRadius = computed(() => {
  const area = Number(result.value.fire_assessment && result.value.fire_assessment.fire_area_m2)
  return Number.isFinite(area) && area > 0 ? Math.max(40, Math.sqrt(area / Math.PI)) : 120
})
const fire3dActive = computed(() => Boolean(result.value.fire_assessment))
const fleetAvgGps = computed(() => {
  const fire = fire3dGps.value
  const origin = analysisResult.value && analysisResult.value.scene ? analysisResult.value.scene.fire_origin : null
  const withPosition = drones.value.filter((drone) => drone.position)
  if (!fire || !origin || !withPosition.length) return fire
  const avg = withPosition.reduce((acc, drone) => ({ x: acc.x + drone.position.x, y: acc.y + drone.position.y }), { x: 0, y: 0 })
  const n = withPosition.length
  return {
    latitude: fire.latitude + (avg.y / n - origin.y) / 111320,
    longitude: fire.longitude + (avg.x / n - origin.x) / (111320 * Math.cos(fire.latitude * Math.PI / 180)),
  }
})
const stations3d = computed(() => {
  const stations = []
  if (fleetAvgGps.value) stations.push({ name: '紫霞湖基地', gps: fleetAvgGps.value, color: '#f0a848' })
  // BE-17：水源全部入三维（名称带距离），上限 4 处防杂乱
  for (const water of waterSourcesList.value.slice(0, 4)) {
    if (!water.coordinates || water.coordinates.longitude == null) continue
    const name = `${water.preferred ? '★ ' : ''}${water.name || '水源'} · ${water.distance != null ? Math.round(water.distance) + 'm' : '距离?'}`.slice(0, 22)
    stations.push({ name, gps: { latitude: Number(water.coordinates.latitude), longitude: Number(water.coordinates.longitude) }, color: water.preferred ? '#5fb8d9' : '#4a9ec2' })
  }
  return stations
})
const evac3dPath = computed(() => {
  const eva = analysisResult.value && analysisResult.value.agent && analysisResult.value.agent.skill_chain
    ? analysisResult.value.agent.skill_chain.evacuation : null
  const origin = analysisResult.value && analysisResult.value.scene ? analysisResult.value.scene.fire_origin : null
  const fire = fire3dGps.value
  if (!eva || !eva.found || !Array.isArray(eva.path) || !origin || !fire) return []
  return eva.path.map(([c, r]) => ({
    latitude: fire.latitude + ((r - 6) * 40) / 111320,
    longitude: fire.longitude + ((c - 6) * 40) / (111320 * Math.cos(fire.latitude * Math.PI / 180)),
  }))
})
// LLM 状态轻量轮询（FE-22 自查优化）：GLM 降级/恢复时头部徽标 30s 内跟上，不写日志
let llmPollTimer = null
async function refreshLlmInfo() {
  try {
    const response = await fetch('/api/llm-status')
    if (response.ok) llmInfo.value = await response.json()
  } catch (error) { /* 瞬时失败保住旧状态 */ }
}

async function loadServiceStatus() {
  try {
    const [healthResponse, statusResponse, llmResponse] = await Promise.all([fetch('/api/health'), fetch('/api/project-status'), fetch('/api/llm-status')])
    if (llmResponse.ok) llmInfo.value = await llmResponse.json()
    if (!healthResponse.ok || !statusResponse.ok) throw new Error('服务状态检查失败')
    serviceOnline.value = true
    projectStatus.value = await statusResponse.json()
    addLog(`后端服务已连接 · v${(await healthResponse.clone().json()).version}`)
  } catch (error) {
    serviceOnline.value = false
    projectStatus.value = { framework: 'local', demo_pipeline: 'ready', yolo: 'pending', vlm: 'pending', geo_data: 'demo-data' }
    addLog('后端服务未连接 · 使用本地演示结果')
    console.warn(error)
  }
}

function acceptFile(fileList) {
  errorMessage.value = ''
  const list = Array.from(fileList || [])
  if (!list.length) return
  const primary = list[list.length - 1]
  const allowed = ['image/jpeg', 'image/png', 'video/mp4']
  if (!allowed.includes(primary.type)) {
    errorMessage.value = '仅支持 JPG、PNG 或 MP4 文件。'
    return
  }
  if (list.some((file) => file.size > 200 * 1024 * 1024)) {
    errorMessage.value = '单个文件大小不能超过 200MB。'
    return
  }
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  selectedFile.value = primary
  // 多选图片时：最新一帧作为主文件，其余图片组成序列帧（api-contract §5.2）。
  selectedFrames.value = primary.type.startsWith('image/') ? list.filter((file) => file.type.startsWith('image/') && file !== primary) : []
  previewUrl.value = URL.createObjectURL(primary)
  uploaded.value = true
  progress.value = 0
  addLog(`已接收航拍影像 · ${primary.name}${selectedFrames.value.length ? ` · 序列共 ${selectedFrames.value.length + 1} 帧` : ''}`)
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function onCapture(file) {
  acceptFile([file])
  addLog('现场采集完成 · 自动进入真实检测与研判链路', { stage: 'ingest', source: 'frontend' })
  startAnalysis()
}

async function startAnalysis() {
  if (analyzing.value) return
  if (!selectedFile.value) {
    errorMessage.value = '请先选择一张火灾图片或一个航拍视频。'
    addLog('研判未启动 · 尚未接入现场影像')
    return
  }

  analyzing.value = true
  taskStatus.value = '分析中'
  currentStage.value = '正在接入现场影像'
  errorMessage.value = ''
  progress.value = 8
  addLog(`研判任务已启动 · ${selectedFile.value.name}`)

  try {
    const stages = [['正在解析航拍影像…', 24, '正在解析影像'], ['规则演示视觉识别完成 · YOLO 对接就绪', 48, '视觉识别（演示）'], ['正在融合风场与地形数据…', 72, '环境融合'], ['正在生成集群调度方案…', 90, '调度生成']]
    for (const [message, value, stage] of stages) {
      await sleep(280)
      addLog(message)
      currentStage.value = stage
      progress.value = value
    }

    const formData = new FormData()
    formData.append('file', selectedFile.value)
    for (const frame of selectedFrames.value) formData.append('frames', frame, frame.name)
    formData.append('scene_id', scene.id)
    formData.append('use_vlm', String(useVlm.value))
    // 人员状态必须随研判上送：有人分支触发疏散路线（规则 V1 §9）
    formData.append('people_status', peopleStatus.value)
    const { latitude, longitude } = environmentForPayload()
    formData.append('latitude', String(latitude))
    formData.append('longitude', String(longitude))
    formData.append('environment_mode', environmentMode.value)
    formData.append('water_search_radius_m', '5000')
    formData.append('road_search_radius_m', '5000')
    const response = await fetch('/api/analyze/upload', { method: 'POST', body: formData })
    if (!response.ok) throw new Error(`分析服务返回 ${response.status}`)
    const payload = await response.json()
    applyEnvelope(payload)
    await loadEvents(analysisId.value)
    if (!analysisResult.value) throw new Error('分析响应缺少 result')
    currentStage.value = '调度方案已生成'
    progress.value = 100
    addLog('研判完成 · 建议立即处置')
  } catch (error) {
    analysisEnvelope.value = null
    analysisResult.value = fallbackResult
    analysisId.value = ''
    stages.value = []
    monitorResult.value = null
    taskStatus.value = '本地演示'
    currentStage.value = '已切换本地演示结果'
    progress.value = 100
    addLog('分析服务暂不可用 · 已切换为本地演示数据')
    errorMessage.value = '分析服务暂不可用，当前展示的是本地演示结果。'
    console.warn(error)
  } finally {
    analyzing.value = false
  }
}

async function runMonitor(auto = false) {
  if (!analysisId.value || monitoring.value) return
  if (auto && (taskStatus.value !== '执行中' || !mission.value?.active)) return
  const monitoredId = analysisId.value
  monitoring.value = true
  let failureDetail = ''
  try {
    // 新集成统一使用 /api/tasks/{id}/rounds（api-contract.md §5.7）；
    // 任务快照始终以后端 Store 为准，不再上送 fleet/inventory。
    // extinguishing_liters=0（FE-41）：不设喷洒上限，由后端状态机按实际出动能力计算——
    // 固定 40L 曾把 4 机 80L/轮的能力砍半，并在喷满 40L 时提前召回在作业机，III 级火永远压不平。
    const roundNumber = (analysisEnvelope.value?.monitor_round || 0) + 1
    const response = await fetch(`/api/tasks/${monitoredId}/rounds`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ round: roundNumber, elapsed_minutes: 5, extinguishing_liters: 0 }) })
    const payload = await response.json().catch(() => ({}))
    if (!response.ok) {
      if (auto && response.status === 409) {
        // 后端权威状态已离开 executing（跨页签终止/状态变更等），本地推演钟分叉：
        // 停钟停画，并重拉任务信封让界面回到真实状态——不弹红错、不再重试
        stopMission(true)
        const resync = await fetch(`/api/analyze/${monitoredId}`)
        if (resync.ok) applyEnvelope(await resync.json())
        addLog(`自动推演已停止 · ${payload?.detail || '任务状态已变更'}`, { stage: 'mission', source: 'rules' })
        return
      }
      failureDetail = payload?.detail || `反馈轮次接口返回 ${response.status}`
      throw new Error(failureDetail)
    }
    if (monitoredId !== analysisId.value) return
    const refreshed = await fetch(`/api/analyze/${monitoredId}`)
    if (refreshed.ok) applyEnvelope(await refreshed.json())
    rounds.value = Array.isArray(analysisEnvelope.value?.rounds) ? analysisEnvelope.value.rounds : rounds.value
    monitorResult.value = payload.after || payload
    reconcileMission(payload.after)
    const action = payload.changes?.action || payload.after?.action || payload.next_action || '保持观察'
    addLog(`第 ${payload.round || roundNumber} 轮反馈完成 · 下一步：${payload.next_action || action} · ${payload.after?.reason || '无重规划原因'}`, { stage: 'monitor', source: 'rules' })
    // FE-42：火情扑灭（finish→completed）立即停自动推演钟——此前 mission.active 未清，
    // 任务条永远卡在「自动推演中 · 第 N 轮」，与后端已完成状态脱节
    if (payload.next_action === 'finish' || action === 'finish' || taskStatus.value === '已完成') {
      stopMission(true)
      addLog('🔥 火情扑灭 · 任务完成归档', { stage: 'mission', source: 'rules' })
    }
    if (payload.after?.replan_required) {
      stopAutoSim()
      addLog('触发重规划 · 自动推演暂停，请在调度建议面板处置', { stage: 'mission', source: 'rules' })
    }
    await loadEvents(monitoredId)
  } catch (error) {
    if (monitoredId === analysisId.value) {
      if (taskStatus.value === '已终止') {
        // 任务已终止：在途轮次作废属预期，静默处理不打扰指挥员
        addLog('任务已终止 · 在途轮次作废', { stage: 'monitor', source: 'frontend' })
      } else {
        errorMessage.value = failureDetail || '反馈轮次暂不可用。'
        addLog('反馈轮次失败 · 保持当前任务状态')
        console.warn(error)
      }
    }
  } finally {
    monitoring.value = false
  }
}

// FE-61：大屏投影模式（放大字号与数据对比度），localStorage 持久化
const projection = ref(localStorage.getItem('fireops-projection') === '1')
function toggleProjection() {
  projection.value = !projection.value
  localStorage.setItem('fireops-projection', projection.value ? '1' : '0')
  document.documentElement.classList.toggle('projection', projection.value)
}
// 出动推演时钟（B-8 二波）：逻辑迁至 composables/useMissionClock.js，onAutoTick 注入自动轮次回调
const { mission, missionNow, simSpeed, setSimSpeed, startMission, stopMission, startAutoSim, stopAutoSim, reconcileMission, missionPhaseText, fireGpsValue } = useMissionClock({
  plan, drones, analysisResult, environmentCoordinates, addLog,
  onAutoTick: () => runMonitor(true),
})

// ---------- 演训模拟（FE-18）：随机火情生成 + 开始模拟 ----------
// BE-19 真实检测状态（阶段一）：skill_chain.fire_perception.observation.detector.data 上屏
const detectorStatus = computed(() => {
  const data = analysisResult.value?.agent?.skill_chain?.fire_perception?.observation?.detector?.data || {}
  if (data.mode !== 'real') return null
  return { mode: data.mode, model: data.model || 'pwm-yolo', source: data.source || 'pwm-yolo-adapter' }
})
const scenario = ref(null)
const scenarioBusy = ref(false)

function fleetAveragePosition() {
  const withPosition = drones.value.filter((drone) => drone.position)
  if (!withPosition.length) return { x: -254, y: -671 }
  return {
    x: withPosition.reduce((sum, drone) => sum + drone.position.x, 0) / withPosition.length,
    y: withPosition.reduce((sum, drone) => sum + drone.position.y, 0) / withPosition.length,
  }
}

function generateScenario() {
  buildScenario(null)
}

// FE-76 演示一键脚本：fixed 非空时跳过随机（主场景=小火速胜；扰动场景=风变+失能固定剧本）
function buildScenario(fixed) {
  resetAnalysis()
  const base = fleetAveragePosition()
  const distance = fixed ? 1200 : 800 + Math.random() * 1700
  const angle = fixed ? ((10 + Math.random() * 30) * Math.PI) / 180 : ((-25 + Math.random() * 100) * Math.PI) / 180
  const fireOrigin = { x: Math.round(base.x + Math.cos(angle) * distance), y: Math.round(base.y + Math.sin(angle) * distance) }
  // FE-43：面积分层抽样——编队持续压制 ≈13 FLP/轮，「生成→扑灭」演示主流程应当多数
  // 落在可胜区间；BE-15：40% 小 / 45% 中 / 15% 大——中火占比上调让多机协同的场面更常见
  // （与后端 /api/scenarios/random 同口径），大火保留 15% 供失控/增援演练
  const sizeRoll = Math.random()
  const areaM2 = fixed ? fixed.areaM2 : Math.round(sizeRoll < 0.4 ? 300 + Math.random() * 600 : sizeRoll < 0.85 ? 900 + Math.random() * 1600 : 2500 + Math.random() * 3500)
  const growthRate = fixed ? fixed.growthRate : Math.round((0.2 + Math.random() * 0.4) * 100) / 100
  const people = fixed ? fixed.people : ['confirmed', 'absent', 'unknown'][Math.floor(Math.random() * 3)]
  const metersPerLng = 111320 * Math.cos((ZIXIAHU_BASE_GPS.latitude * Math.PI) / 180)
  const fireGps = {
    latitude: +(ZIXIAHU_BASE_GPS.latitude + (fireOrigin.y - base.y) / 111320).toFixed(6),
    longitude: +(ZIXIAHU_BASE_GPS.longitude + (fireOrigin.x - base.x) / metersPerLng).toFixed(6),
  }
  peopleStatus.value = people
  // 演练互斥（FE-34/35）：风变重规划可能生成无灭火机方案，与失能演练语义冲突，二选一
  const drillRoll = Math.random()
  const failureRound = fixed ? fixed.failureRound : (drillRoll < 0.35 ? 2 + Math.floor(Math.random() * 3) : null)
  // FE-44：风变目标必须真跨档（档位 0-4/4-6/6-8/8+）——旧逻辑 base+2.5 在低风天
  // 仍同档（1.35→3.9 同在 band 0），风变重规划静默失效；按基准档位取下一档中值
  const baseWind = Number(result.value.environment.wind_speed) || 0
  const windShift = fixed ? fixed.windShift : (failureRound ? null : (Math.random() < 0.4 ? { round: 2 + Math.floor(Math.random() * 3), speed: baseWind < 4 ? 5.5 : baseWind < 6 ? 7.5 : baseWind < 8 ? 8.6 : 5.2 } : null))
  scenario.value = { fireOrigin, fireGps, areaM2, growthRate, people, failureRound, windShift }
  const peopleLabel = people === 'confirmed' ? '在场' : people === 'absent' ? '不在场' : '情况不明'
  addLog(`随机火情已生成 · 面积 ${areaM2}m² · 人员${peopleLabel} · 演训模拟就绪`, { stage: 'scenario', source: 'local' })
  // 环境预取（随机坐标必缓存未命中，实抓气象/水源/路网可耗时 1-2 分钟）：
  // 生成即后台拉取，开始模拟时命中缓存或在途请求合并（后端 single-flight 去重），
  // 演训与演示都不再在「开始模拟」后长等。fire-and-forget，失败静默（分析端有兜底）。
  fetch(`/api/environment?latitude=${fireGps.latitude}&longitude=${fireGps.longitude}&environment_mode=real`)
    .then((response) => {
      if (response.ok) addLog('演训火点环境数据已就绪', { stage: 'scenario', source: 'local' })
    })
    .catch(() => {})
}

function loadDemoMain() {
  buildScenario({ areaM2: 450, growthRate: 0.18, people: 'absent', failureRound: null, windShift: null })
  addLog('演示脚本 · 主场景：小火速胜闭环', { stage: 'scenario', source: 'local' })
  startScenarioSimulation()
}

function loadDemoPerturb() {
  const baseWind = Number(result.value.environment.wind_speed) || 0
  buildScenario({
    areaM2: 1800, growthRate: 0.45, people: 'unknown',
    failureRound: null,
    windShift: { round: 2, speed: baseWind < 4 ? 5.5 : baseWind < 6 ? 7.5 : baseWind < 8 ? 8.6 : 5.2 },
  })
  addLog('演示脚本 · 扰动场景：风变跨档触发重规划', { stage: 'scenario', source: 'local' })
  startScenarioSimulation()
}

const scenarioPreview = computed(() => {
  if (!scenario.value || analysisResult.value) return null
  return { gps: scenario.value.fireGps, areaM2: scenario.value.areaM2, radiusMeters: Math.max(40, Math.sqrt(scenario.value.areaM2 / Math.PI)) }
})

async function startScenarioSimulation() {
  if (!scenario.value || scenarioBusy.value || analyzing.value) return
  scenarioBusy.value = true
  analyzing.value = true
  taskStatus.value = '分析中'
  currentStage.value = '正在生成演训火情'
  errorMessage.value = ''
  addLog(`演训模拟启动 · 火点 ${scenario.value.fireGps.longitude}°E, ${scenario.value.fireGps.latitude}°N`)
  try {
    const response = await fetch('/api/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
      scene_id: scene.id,
      latitude: scenario.value.fireGps.latitude,
      longitude: scenario.value.fireGps.longitude,
      environment_mode: environmentMode.value,
      people_status: scenario.value.people,
      fire_type: 'vegetation',
      scenario: { fire_origin: scenario.value.fireOrigin, fire_area_m2: scenario.value.areaM2, growth_rate: scenario.value.growthRate, uav_failure_round: scenario.value.failureRound, wind_shift: scenario.value.windShift },
    }) })
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}))
      throw new Error(detail?.detail || `模拟服务返回 ${response.status}`)
    }
    applyEnvelope(await response.json())
    await loadEvents(analysisId.value)
    currentStage.value = '调度方案已生成'
    addLog('演训火情研判完成 · 等待批准出动')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '演训模拟失败，请重试。'
    addLog('演训模拟失败 · 请重试')
    taskStatus.value = '待命'
    currentStage.value = '等待重新开始模拟'
    console.warn(error)
  } finally {
    scenarioBusy.value = false
    analyzing.value = false
  }
}
// ---------- 演训模拟结束 ----------

function resetAnalysis() {
  analysisEnvelope.value = null
  analysisResult.value = null
  analysisId.value = ''
  stages.value = []
  currentStage.value = '等待影像接入'
  rounds.value = []
  selectedFile.value = null
  selectedFrames.value = []
  closeEventStream()
  stopMission(false)
  mission.value = null
  agentMessages.value = []
  uploaded.value = false
  progress.value = 0
  errorMessage.value = ''
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
  addLog('已清空当前影像 · 等待新的侦察数据')
}

function onKeydown(event) {
  if (event.key === 'Escape') {
    if (activeMarker.value) { activeMarker.value = null; return }
    if (reportViewer.value.open) reportViewer.value.open = false
    return
  }
  // FE-64 快捷键：P 投影模式 / V 语音静音（输入控件聚焦时跳过）
  const tag = event.target?.tagName
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return
  if (event.key === 'p' || event.key === 'P') { toggleProjection(); return }
  if (event.key === 'v' || event.key === 'V') { toggleVoice(); return }
}

onMounted(() => { window.addEventListener('commander-auth-required', onCommanderAuthRequired) })
// FE-78 录屏预热（审计§六步骤 6）：空闲时预载三维 chunk + 预取默认地形网格，
// 首次切三维无加载停顿；不改变任何显示逻辑
onMounted(() => {
  const prewarm = () => {
    import('./components/Terrain3D.vue').catch(() => {})
    const { latitude, longitude } = environmentCoordinates.value
    const key = `${latitude.toFixed(5)},${longitude.toFixed(5)}`
    fetch(`/api/terrain/grid?latitude=${latitude}&longitude=${longitude}&radius_deg=0.06&size=161`)
      .then((r) => (r.ok ? r.json() : null))
      .then((grid) => {
        // 与 loadTerrainGrid 同键控：预热即生效，切三维零等待
        if (grid && grid.status === 'ok' && !terrainGrid.value) {
          terrainGrid.value = grid
          terrainGridKey.value = key
        }
      })
      .catch(() => {})
  }
  if ('requestIdleCallback' in window) requestIdleCallback(prewarm, { timeout: 8000 })
  else setTimeout(prewarm, 3000)
})
onBeforeUnmount(() => { window.removeEventListener('commander-auth-required', onCommanderAuthRequired) })
onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  refreshLlmInfo()
  llmPollTimer = window.setInterval(refreshLlmInfo, 30000)
  document.documentElement.classList.toggle('projection', projection.value)
  tickWallClock()
  wallTimer = window.setInterval(tickWallClock, 1000)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  if (llmPollTimer) { window.clearInterval(llmPollTimer); llmPollTimer = null }
  if (wallTimer) { window.clearInterval(wallTimer); wallTimer = null }
  closeEventStream()
  stopMission(false)
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})

onMounted(() => {
  loadServiceStatus()
  loadTerrainGrid()
  loadFleetAndInventory()
  loadEnvironment()
  loadContours()
  refreshWeather(environmentCoordinates.value)
})
</script>

<template>
  <div class="app-shell">
  <header class="topbar">
    <div class="brand"><div class="brand-mark"><Flame :size="19" /></div><div><strong>火巡智策</strong><small>FOREST FIRE COMMAND</small></div></div>
    <div class="topbar-divider"></div>
    <div class="topbar-title"><h1>森林火灾智能应急指挥平台</h1><p class="slogan">智慧感知 · 协同决策 · 快速响应 · 守护生态</p></div>
    <div class="topbar-right">
      <span class="topbar-scene" :title="`${scene.name} · ${scene.incident}`"><MapPinned :size="14" /> {{ scene.name }}<i>当前任务 · {{ scene.incident }}</i></span>
      <span class="task-badge" :title="currentStage">任务状态 · {{ displayStatus }}</span>
      <span v-if="weather" class="weather-chip" :title="weatherTitle"><component :is="weatherIcon" :size="15" /> {{ weather.text }} {{ weather.temperature }}°C<i>湿度 {{ weather.humidity }}%</i></span>
      <button :class="['icon-btn', { proj: projection }]" :aria-pressed="projection" title="大屏投影模式（放大字号与数据对比度）" @click="toggleProjection"><MonitorUp :size="18" /></button>
      <button class="icon-btn" aria-label="告警与任务日志" title="查看告警与任务事件通知" @click="selectNav('logs')"><Bell :size="18" /><i v-if="alarms.length"></i></button>
      <div class="utc">{{ wallDate }}<br><strong>{{ wallTime }}</strong></div>
      <div class="topbar-user" title="当前指挥员 · 江月（OP-07）"><div class="avatar">江</div><div><strong>江月</strong><small>指挥员</small></div></div>
    </div>
  </header>
  <aside class="sidebar">
      <nav aria-label="主导航"><button v-for="item in navItems" :key="item.id" :class="{ active: activeTab === item.id }" @click="selectNav(item.id)"><component :is="item.icon" :size="17" /><span>{{ item.label }}</span><b v-if="item.id === 'fleet'">{{ drones.length }}</b></button></nav>
      <div class="sidebar-foot"><div class="system-status"><span :class="['live-dot', { offline: !serviceOnline }]" /><div><strong>{{ serviceOnline ? '系统运行正常' : '本地演示模式' }}</strong><small>{{ serviceOnline ? '后端服务在线' : '后端服务未连接' }}</small></div></div><div class="operator"><div class="avatar">江</div><div><strong>江月</strong><small>指挥员 · OP-07</small></div><ChevronRight :size="16" /></div></div>
  </aside>

    <main :class="{ 'main-map': activeTab === 'map' }">
    <div v-if="authRequired" class="auth-gate" role="alert">
      <span>后端已开启指挥员口令校验</span>
      <input v-model="authTokenInput" type="password" placeholder="输入指挥员口令" @keyup.enter="saveCommanderToken">
      <button class="primary" @click="saveCommanderToken">保存并继续</button>
      <button class="outline-btn" @click="authRequired = false">稍后</button>
    </div>
    <div v-if="alarms.length" class="alarm-stack" role="alert">
      <div v-for="alarm in alarms" :key="alarm.id" :class="['alarm-card', alarm.level]">
        <div class="alarm-head"><i></i>{{ alarm.time }}<button class="alarm-close" @click="dismissAlarm(alarm.id)">×</button></div>
        <p>{{ alarm.text }}</p>
      </div>
    </div>
      <div v-if="errorMessage" class="notice" role="status"><Activity :size="16" /><span>{{ errorMessage }}</span><button v-if="canRetryAnalysis" class="outline-btn notice-retry" :disabled="analyzing" @click="startAnalysis">重试研判</button><button class="notice-close" title="关闭提示" @click="errorMessage = ''">×</button></div>

      <template v-if="activeTab === 'command'">
      <div class="page-head fm-head"><div><h2>火情监测</h2><p>接入现场影像 · YOLO / VLM 负责视觉观察，FLP 与安全关键数值由规则引擎计算</p></div><span v-if="dataMode" class="fm-data-mode">{{ dataMode }}</span></div>
      <div class="monitor-grid">
        <div class="monitor-left">
        <MonitorVideoStage v-model:show-boxes="evidenceShowBoxes" v-model:active-index="activeFrameIndex" :preview-url="previewUrl" :frames="frameStrip" :boxes="evidenceView" :analyzing="analyzing" :progress="progress" :uploaded="uploaded" :file-name="selectedFile?.name || ''" :captured-at="stageCapturedAt" :quality="stageQuality" :uav-label="result.agent?.skill_chain?.fire_perception?.observation?.source_uav || 'R1'" @files="acceptFile" @capture="onCapture" @reset="resetAnalysis" />
        <details class="fm-tools-drawer" :open="toolsOpen" @toggle="onToolsToggle">
          <summary>影像接入工具 · 分析管线 · 演训模拟</summary>
          <UploadPanel :analyzing="analyzing" :progress="progress" :uploaded="uploaded" :preview-url="previewUrl" :selected-file="selectedFile" :selected-frames="selectedFrames" :project-status="projectStatus" :llm-available="Boolean(llmInfo?.available)" :llm-model="llmInfo?.model || ''" :environment-coordinates="environmentCoordinates" :scenario="scenario" :scenario-busy="scenarioBusy" v-model:use-vlm="useVlm" :detector-status="detectorStatus" @files="acceptFile" @capture="onCapture" @reset="resetAnalysis" @generate-scenario="generateScenario" @start-scenario="startScenarioSimulation" @demo-main="loadDemoMain" @demo-perturb="loadDemoPerturb" />
        </details>
        </div>
        <div class="monitor-right">
        <section class="panel fm-card" aria-label="火情识别结果"><div class="panel-heading"><h2>火情识别结果</h2><span class="log-count">视觉观察 · YOLO / VLM</span></div>
          <div class="fm-rows">
            <span v-for="row in recognitionRows" :key="row.k" class="fm-row"><i>{{ row.k }}</i><b :class="row.tone">{{ row.v }}</b></span>
          </div>
          <p v-if="vlmNoteBody" class="fm-summary"><i>VLM 摘要</i>{{ vlmNoteBody }}</p>
          <ul v-if="vlmNoteIssues.length" class="vlm-note-issues"><li v-for="(issue, i) in vlmNoteIssues" :key="i">需人工复核 · {{ issue }}</li></ul>
          <div class="model-badges"><span v-for="badge in modelBadges" :key="badge.name" :class="{ ok: badge.ok }"><b>{{ badge.name }}</b>{{ badge.state }}<small>{{ badge.detail }}</small></span></div>
        </section>
        <section class="panel fm-card" aria-label="火情量化"><div class="panel-heading"><h2>火情量化</h2><span :class="['dt-chip', controlVerdictView.tone === 'ok' ? 'ok' : controlVerdictView.tone === 'mid' ? 'orange' : 'red']">{{ controlVerdictView.hint }}</span></div>
          <div class="fm-rows">
            <span v-for="row in quantifyRows" :key="row.k" class="fm-row"><i>{{ row.k }}</i><b :class="row.tone">{{ row.v }}</b></span>
          </div>
          <p class="src-note">YOLO / VLM 负责视觉观察 · FLP 与安全关键数值由规则引擎计算</p>
        </section>
        <section class="panel fm-card environment-panel" aria-label="环境影响"><div class="panel-heading"><h2>环境影响</h2><button class="outline-btn environment-refresh" :disabled="environmentLoading" @click="loadEnvironment"><RefreshCw :size="14" /> {{ environmentLoading ? '刷新中…' : '刷新环境' }}</button></div>
          <div class="environment-grid"><div v-for="item in environmentFeatures" :key="item.label" class="environment-item"><span>{{ item.label }}</span><strong :class="['tone-' + item.tone, { 'is-empty': item.empty }]">{{ item.value }}</strong></div></div>
          <div class="environment-meta"><span>数据来源 · {{ environmentSource }}</span><span>更新时间 · {{ environment?.collected_at?.slice(0, 19).replace('T', ' ') || '—' }}{{ environmentAgeText ? '（' + environmentAgeText + '）' : '' }}</span></div>
          <p class="environment-note src-note">决策作用 · 坡度→K_slope · 燃料→K_fuel · 风速→K_wind/风档（参与 FLP 计算）；温湿度为背景信息不参与计算</p>
          <details class="fm-env-controls"><summary>模式与坐标</summary>
            <div class="environment-controls"><label>模式 <select v-model="environmentMode" @change="loadEnvironment"><option value="real">真实数据</option><option value="auto">自动</option><option value="offline">离线演示（不联网）</option><option value="demo">演示数据</option></select></label><div class="coordinate-editor"><label>纬度 <input v-model="coordinateDraft.latitude" inputmode="decimal" aria-label="纬度"></label><label>经度 <input v-model="coordinateDraft.longitude" inputmode="decimal" aria-label="经度"></label><button class="outline-btn" type="button" @click="applyCoordinates">应用</button></div><span>{{ environmentCoordinates.latitude.toFixed(6) }}, {{ environmentCoordinates.longitude.toFixed(6) }}</span></div>
            <div v-if="coordinateError" class="coordinate-error" role="alert">{{ coordinateError }}</div>
          </details>
        </section>
        </div>
      </div>
      <div class="fm-trend-section" aria-label="趋势分析">
        <div class="fm-trend-head"><h3>趋势分析</h3><span class="log-count">面积出自影像序列 · FLP 与风速出自轮次账本</span><span v-if="frameTrendText" class="fm-frame-trend">{{ frameTrendText }}</span></div>
        <TrendStrip :frames="frameStrip" :visual-sequence="result?.visual_sequence || null" :rounds="activeRounds" :people-status="peopleStatus" :wind-now="result.environment?.wind_speed ?? null" :fire-area-now="monitorArea" />
      </div>
      <div class="fm-action-bar" role="toolbar" aria-label="火情监测操作">
        <button class="primary fm-ab-analyze" :disabled="analyzing || !selectedFile" @click="startAnalysis"><Bot :size="16" /> 开始研判</button>
        <button class="outline-btn fm-ab-people" @click="cyclePeopleStatus" title="点击切换：不确定 → 无人 → 有人">确认人员状态 · {{ { confirmed: '有人', absent: '无人', unknown: '不确定' }[peopleStatus] }}</button>
        <button class="outline-btn fm-ab-fix" :disabled="!uploaded" @click="resetAnalysis"><RefreshCw :size="14" /> 修正观察结果</button>
        <button class="fm-ab-dispatch" @click="gotoDispatchPlan">生成调度方案 <ChevronRight :size="14" /></button>
        <template v-if="analysisEnvelope && analysisEnvelope.status === 'awaiting_confirmation'">
          <span class="ma-gap"></span>
          <button class="primary" :disabled="approvalBusy" @click="submitApproval('approve')">批准主方案</button>
          <button class="outline-btn danger-btn" :disabled="approvalBusy" @click="submitApproval('terminate', { defaultReason: '指挥员在火情监测页终止任务' })">终止任务</button>
        </template>
        <p class="people-risk-line">{{ peopleRisk }}</p>
      </div>
      </template>

      <template v-else-if="activeTab === 'dispatch'">
      <div class="page-head"><div><h2>机群调度</h2><p>{{ scene.name }} · {{ scene.incident }} —— 方案版本与硬约束 · 审批与调整 · 轮次推演账本与回放复盘</p></div><span class="task-badge" v-if="displayStatus">任务状态 · {{ displayStatus }}</span></div>
      <div class="dispatch-grid2">
        <div class="dispatch-map-col">
          <div class="tactical-map-wrap dispatch-map" @click="dismissMarker">
            <div v-if="analysisResult && analysisResult.fire_assessment" :class="['dispatch-alert-card', 'lvb-' + fireLevelNum]" role="status" aria-label="火情告警">
              <div class="dac-head"><span class="dac-flame"><Flame :size="14" /></span><b>{{ result.fire_assessment.label }}</b></div>
              <div class="dac-rows">
                <span>发现时间<b>{{ (analysisEnvelope?.created_at || '').slice(0, 19).replace('T', ' ') || '—' }}</b></span>
                <span>过火面积<b>{{ formatNumber(result.fire_assessment.fire_area_m2) }} m²</b></span>
                <span>火场位置<b>{{ environmentCoordinates.longitude.toFixed(4) }}°E, {{ environmentCoordinates.latitude.toFixed(4) }}°N</b></span>
                <span>火势风向<b>{{ result.environment.wind_direction || '—' }}风 {{ result.environment.wind_speed ?? '—' }} m/s</b></span>
              </div>
            </div>
            <TacticalMap v-if="amapReady" ref="tacticalMapRef" :result="result" :environment="environment" :drones="drones" :water-list="waterSourcesList" :contours="contourData" :layer-visibility="layerVisibility" :selected-uavs="(analysisResult?.dispatch_plan?.selected_uavs || [])" :mission="mission" :scenario-preview="scenarioPreview" :focus-pulse="focusPulse" :hovered-drone-id="hoveredDroneId" :hovered-water-id="hoveredWaterId" :active-marker-id="activeMarker?.id || ''" :default-center="environmentCoordinates" :pick-mode="pickMode" @select-marker="selectMarker" @coords="cursorCoords = $event" @pick-coords="applyPickedCoords" @ready="addLog('高德卫星底图加载完成')" @fallback="onAmapFallback" />
            <template v-else>
              <EvolutionChart :rounds="activeRounds" />
              <section class="panel dispatch-res-panel"><div class="panel-heading"><h2>资源消耗</h2><span class="log-count">累计自轮次监测</span></div><div v-if="activeRounds.length" class="resource-strip dispatch-strip"><span>水消耗 <b>{{ resourceSummary.water }}</b> L</span><span>CO₂ <b>{{ resourceSummary.co2 }}</b> kg</span><span>换电 <b>{{ resourceSummary.swaps }}</b> 次</span><span>补给 <b>{{ resourceSummary.refills }}</b> 次</span></div><div v-else class="empty-hint"><b>暂无轮次</b>批准方案并推演后，药剂与保障消耗会在这里累计。</div></section>
            </template>
          </div>
        </div>
        <div class="dispatch-right">
        <DecisionPanel :preview-url="previewUrl" :analysis-result="analysisResult" :disable-options="disableOptions" :max-drones-options="maxDronesOptions" :result="result" :analysis-envelope="analysisEnvelope" :analysis-id="analysisId" :active-rounds="activeRounds" :monitor-result="monitorResult" :monitor-area="monitorArea" :data-mode="dataMode" :control-verdict-view="controlVerdictView" :plan-version-label="planVersionLabel" :current-plan-id="currentPlanId" :control-window="controlWindow" :resource-gap="resourceGap" :evacuation-summary="evacuationSummary" :people-risk="peopleRisk" :vlm-note="vlmNote" :vlm-note-source="vlmNoteSource" :vlm-note-body="vlmNoteBody" :vlm-note-facts="vlmNoteFacts" :vlm-note-issues="vlmNoteIssues" :frame-trend-text="frameTrendText" :input-provenance-text="inputProvenanceText" :mission-active="mission?.active" :mission-now="missionNow" :approval-busy="approvalBusy" :monitoring="monitoring" :soc-warn-list="socWarnList" v-model:people-status="peopleStatus" v-model:max-drones="maxDrones" v-model:target-minutes="targetMinutes" v-model:disabled-uavs="disabledUavs" v-model:reason-input="reasonInput" v-model:sim-speed="simSpeed" v-model:report-open="reportViewer.open" @approval="submitApproval" @monitor="runMonitor()" @set-speed="setSimSpeed" @error="errorMessage = $event" />
          <section class="panel dispatch-squadron"><div class="panel-heading"><h2>机群编组</h2><span class="log-count">2 + 6 + 4 资源池 · 状态实时</span><button class="text-btn" @click="selectNav('fleet')">完整名册 <ChevronRight :size="14" /></button></div><div class="squadron-tables dsp3"><div v-for="group in squadronTable" :key="group.key" class="group-table-card"><div :class="['group-table-head', group.cls]"><b>{{ group.label.replace('单元', '组') }}</b><small>{{ group.rows.length }} 架</small></div><div class="gt-scroll"><table class="data-table"><thead><tr><th>机号</th><th>当前任务</th><th class="num">SOC</th><th>状态</th></tr></thead><tbody><tr v-for="drone in group.rows" :key="drone.id"><td class="num"><i :class="['gt-dot', drone.status === '待命' ? 'idle' : ['故障', '离线'].includes(drone.status) ? 'fault' : drone.status.includes('返航') ? 'ret' : 'busy']"></i><b :style="{ color: SUBGROUP_COLORS[group.key] }">{{ drone.id }}</b></td><td :title="drone.task" class="gt-task">{{ drone.task }}</td><td class="num">{{ drone.soc }}%</td><td><span :class="['dt-chip', drone.status === '待命' ? 'slate' : ['故障', '离线'].includes(drone.status) ? 'red' : 'ok']">{{ drone.status }}</span></td></tr></tbody></table></div></div></div></section>
        </div>
      </div>
      <div class="round-bar" role="status" aria-label="轮次与重规划">
        <span class="rb-title">轮次与重规划</span>
        <div class="rb-cell"><small>当前轮次</small><b>{{ activeRounds.length ? `第 ${activeRounds.length} 轮` : '未开始' }}</b></div>
        <div class="rb-cell"><small>下次评估</small><b>{{ mission?.active ? `自动推演 ${Math.floor(missionNow % 5)}/5 min` : (taskStatus === '执行中' ? '可手动执行' : '—') }}</b></div>
        <div class="rb-cell"><small>风向风速</small><b>{{ result.environment.wind_direction || '—' }}风 {{ result.environment.wind_speed ?? '—' }} m/s</b></div>
        <div class="rb-cell"><small>SOC 预警</small><b :class="{ warn: socWarnList.length }">{{ socWarnList.length ? socWarnList.join('、') : '无' }}</b></div>
        <div class="rb-cell"><small>补给缺口</small><b :class="{ warn: resourceGap.length }">{{ resourceGap.length ? resourceGap.map((gap) => gap.name || gap.resource || gap.type).join('、') : '无' }}</b></div>
        <div class="rb-cell"><small>单机故障</small><b :class="{ bad: faultList.length }">{{ faultList.length ? faultList.join('、') : '无' }}</b></div>
        <div class="rb-cell"><small>人员状态</small><b>{{ { confirmed: '有人', absent: '无人', unknown: '不确定' }[peopleStatus] || '—' }}</b></div>
        <div class="rb-cell"><small>重规划原因</small><b :class="{ warn: latestReplanReason !== '无' }" :title="latestReplanReason">{{ latestReplanReason }}</b></div>
        <div class="rb-cell"><small>方案版本</small><span class="rb-versions"><span v-for="version in planVersionsList" :key="version.label" :class="{ cur: version.current }">{{ version.label }}</span><span v-if="!planVersionsList.length">V1</span></span></div>
        <div class="rb-cell"><small>决策过程</small><b class="ok" style="cursor:pointer" @click="decisionFold = !decisionFold">{{ decisionFold ? '收起决策过程' : (agentMessages.length ? `${agentMessages.length} 条协作消息` : '查看决策过程') }}</b></div>
      </div>
      <section :class="['decision-fold', { open: decisionFold }]" aria-label="决策过程">
        <button class="decision-fold-head" :aria-expanded="decisionFold" @click="decisionFold = !decisionFold"><Bot :size="16" /> Agent 协作 · 决策过程<small>{{ agentMessages.length }} 条黑板协作消息 · 六角色实时研判</small><ChevronRight :size="16" class="fold-arrow" /></button>
        <div v-if="decisionFold" class="decision-fold-body">
          <div class="fold-cols">
            <div class="full-logs agent-timeline fold-stream">
              <div v-if="!agentMessages.length" class="agents-empty"><p class="agents-empty-lead"><b>暂无协作消息</b>启动研判或演训模拟后，六个角色通过黑板协议实时协作，消息流将按时间显示在这里。</p><div class="agents-roles"><div class="agents-role"><b>指挥官</b><span>建案派任务 · 审批仲裁</span></div><div class="agents-role"><b>侦察单元</b><span>态势发现 · 影像判读</span></div><div class="agents-role"><b>灭火单元</b><span>主力压制 · 补位接替</span></div><div class="agents-role"><b>支援单元</b><span>物资补给 · 通信中继</span></div><div class="agents-role"><b>仿真评估</b><span>逐轮研判 · 趋势闸门</span></div><div class="agents-role"><b>交互审批</b><span>方案确认 · 驳回调整</span></div></div></div>
              <div v-for="message in agentMessages" :key="message.seq" class="agent-msg"><span class="agent-avatar" :class="'av-' + message.frm">{{ String(message.frm || '?').slice(0, 1).toUpperCase() }}</span><span class="log-time">{{ message.ts?.slice(11) || message.ts }}</span><b class="agent-chip" :class="'mt-' + message.msg_type">{{ agentMsgLabel(message.msg_type) }}</b><div class="agent-msg-body"><strong>{{ message.frm }} → {{ message.to }}</strong><p>{{ message.content }}</p></div><small class="agent-source" :class="'src-' + message.source">{{ agentSourceLabel(message.source) }}</small></div>
            </div>
            <section class="panel chat-panel fold-chat"><div class="panel-heading"><h2>指挥员问答</h2><span class="status-tag" :class="llmInfo?.available ? '' : 'orange'">{{ llmInfo?.available ? 'GLM 在线' : '离线 · 规则回答' }}</span></div><ChatPanel :task-id="analysisId" :enabled="chatEnabled" /></section>
          </div>
        </div>
      </section>
      </template>

      <section v-else-if="activeTab === 'fleet'" class="detail-view"><div class="detail-heading"><div><h2>资源总览</h2><p>无人机、药剂与补给资源实时状态 · 数据来自 /api/fleet 与 /api/inventory</p></div><span class="status-tag"><span class="live-dot"></span> 全部在线</span></div>
        <div class="res-kpis">
          <div class="res-kpi"><span class="rk-icon"><Plane :size="19" /></span><div><b>{{ fleetStatusCounts.total }}<small>架</small></b><span>无人机总数</span></div></div>
          <div class="res-kpi tone-green"><span class="rk-icon"><Play :size="17" /></span><div><b>{{ fleetStatusCounts.available }}<small>架</small></b><span>可用数量</span></div></div>
          <div class="res-kpi tone-blue"><span class="rk-icon"><Target :size="18" /></span><div><b>{{ fleetStatusCounts.busy }}<small>架</small></b><span>执行任务</span></div></div>
          <div class="res-kpi"><span class="rk-icon"><RefreshCw :size="17" /></span><div><b>{{ fleetStatusCounts.returning }}<small>架</small></b><span>返航中</span></div></div>
          <div class="res-kpi"><span class="rk-icon"><Settings :size="17" /></span><div><b>{{ fleetStatusCounts.maintain }}<small>架</small></b><span>维护中</span></div></div>
          <div class="res-kpi tone-ember"><span class="rk-icon"><Zap :size="18" /></span><div><b>{{ fleetStatusCounts.fault }}<small>架</small></b><span>故障数量</span></div></div>
          <div class="res-kpi tone-blue"><span class="rk-icon"><Droplets :size="18" /></span><div><b>{{ inventory?.water_modules_w20 ?? '—' }}<small>模块</small></b><span>W20 库存</span></div></div>
          <div class="res-kpi tone-blue"><span class="rk-icon"><Droplets :size="18" /></span><div><b>{{ inventory?.co2_modules_c6 ?? '—' }}<small>罐</small></b><span>C6 库存</span></div></div>
          <div class="res-kpi"><span class="rk-icon"><BatteryCharging :size="18" /></span><div><b>{{ inventory?.battery_packs ?? '—' }}<small>块</small></b><span>备用电池</span></div></div>
          <div class="res-kpi tone-green"><span class="rk-icon"><Droplets :size="18" /></span><div><b>{{ fleetStatusCounts.water }}<small>处</small></b><span>可用水源</span></div></div>
        </div>
        <div class="res-section-head"><h3>无人机资源池（2 + 6 + 4）</h3><span class="res-tip">ⓘ 此页面展示资源事实与状态，不生成调度方案</span></div>
        <div class="fleet-roster"><div v-for="group in fleetGroups" :key="group.key" class="roster-group"><div :class="['group-table-head', group.key === 'reconnaissance' ? 'gt-blue' : group.key === 'suppression' ? 'gt-orange' : 'gt-green', 'roster-group-head']"><b>{{ group.label }}</b><small>{{ group.drones.length }} 架 · {{ group.role }}</small></div><div class="drone-cards"><div v-for="drone in group.drones" :key="drone.id" class="drone-card"><div class="dc-head"><span class="dc-icon" :style="{ color: SUBGROUP_COLORS[group.key] || '#8fa39a' }"><svg class="node-quad dc-quad" viewBox="0 0 40 40"><circle class="nq-track" cx="20" cy="20" r="15.5"/><circle class="nq-arc" cx="20" cy="20" r="15.5" transform="rotate(-90 20 20)" :stroke-dasharray="quadDash(drone.soc)"/><path class="nq-arms" d="M13 13 L27 27 M27 13 L13 27"/><circle class="nq-body" cx="20" cy="20" r="5"/></svg></span><div class="dc-id"><b>{{ drone.id }}</b><span>{{ group.label.replace('单元', '组') }} · {{ drone.label }}</span></div><span :class="['dt-chip', statusToneClass(drone.status)]">{{ drone.status }}</span></div><div class="dc-fields"><span><i>SOC</i><b>{{ drone.soc }}%</b></span><span><i>健康状态</i><b :class="{ ok: drone.health >= 97 }">{{ drone.health >= 97 ? '良好' : drone.health >= 90 ? '正常' : '注意' }}</b></span><span><i>信号强度</i><b>{{ drone.signal >= 95 ? '强' : '正常' }} · {{ drone.signal }}%</b></span><span><i>载荷容量</i><b>{{ drone.payload_capacity_kg ?? '—' }} kg</b></span><span><i>当前载荷</i><b>{{ moduleLabel(drone.module) }}</b></span><span><i>剩余 W20</i><b>{{ droneAgentLeft(drone, 'water') }}</b></span><span><i>剩余 C6</i><b>{{ droneAgentLeft(drone, 'co2') }}</b></span><span><i>当前任务</i><b class="dc-task" :title="drone.task">{{ drone.task }}</b></span><span><i>预计返航时间</i><b>{{ droneEtaText(drone) }}</b></span><span><i>任务锁定</i><b>{{ (analysisResult?.dispatch_plan?.selected_uavs || []).includes(drone.id) ? '是 · 方案' : '否' }}</b></span></div><div class="dc-foot"><button class="outline-btn" @click="toggleFleetDetail(drone.id)"><ListFilter :size="14" /> {{ expandedFleet.has(drone.id) ? '收起遥测' : '遥测' }}</button></div><div v-if="expandedFleet.has(drone.id)" class="fleet-detail-extra dc-extra"><span>速度 {{ drone.speed_mps ?? '—' }} m/s</span><span>耗电 {{ drone.energy_rate_percent_per_hour ?? '—' }} %/h</span><span>高度 {{ (drone.position && drone.position.z != null) ? drone.position.z + ' m' : '—' }}</span><span>编号 {{ drone.uav_id || drone.id }}</span><span>任务 {{ drone.task }}</span></div></div></div></div></div>
        <div class="fleet-bottom-grid">
          <section class="panel inv-panel"><div class="panel-heading"><h2>物资库</h2><span class="log-count">来自 /api/inventory</span></div><table class="data-table"><thead><tr><th>物资名称</th><th class="num">库存总量</th><th class="num">已占用</th><th class="num">可用数量</th><th class="num">安全库存</th><th>补充预警</th><th>操作状态</th></tr></thead><tbody><tr v-for="row in inventoryRows" :key="row.key"><td>{{ row.name }}<small v-if="row.note" class="cell-note">{{ row.note }}</small></td><td class="num"><b>{{ row.total }}</b> {{ row.unit }}</td><td class="num">{{ row.occupied }}</td><td class="num"><b :class="{ warn: row.low }">{{ row.available }}</b></td><td class="num">{{ row.safety }} {{ row.unit }}</td><td><span :class="['dt-chip', row.low ? 'red' : 'ok']">{{ row.low ? '低于安全库存' : '库存充足' }}</span></td><td><span :class="['dt-chip', row.low ? 'orange' : 'ok']">{{ row.low ? '需补充' : '正常' }}</span></td></tr></tbody></table></section>
          <section class="panel water-table-panel"><div class="panel-heading"><h2>水源与驻防点</h2><span class="log-count">{{ waterSourcesList.length }} 处 · 按距离排序</span></div><table v-if="waterSourcesList.length" class="data-table"><thead><tr><th>名称</th><th class="num">距离</th><th>水源类型</th><th>候选/已核验</th><th>安全状态</th><th>容量状态</th><th>用于当前方案</th><th>所属驻防点</th></tr></thead><tbody><tr v-for="water in waterSourcesList.slice(0, 8)" :key="water.id"><td>{{ water.preferred ? '★ ' : '' }}{{ water.name }}</td><td class="num">{{ waterDistanceText(water) }}</td><td>{{ water.type }}</td><td><span :class="['dt-chip', water.verified ? 'ok' : 'slate']">{{ water.verified ? '已核验' : '候选' }}</span></td><td><span :class="['dt-chip', water.safety === true ? 'ok' : water.safety === false ? 'red' : 'slate']">{{ water.safety === true ? '安全' : water.safety === false ? '不安全' : '待评估' }}</span></td><td>{{ water.capacity != null ? formatNumber(water.capacity) + ' L' : '未知' }}</td><td><span :class="['dt-chip', water.preferred ? 'blue' : 'slate']">{{ water.preferred ? '是 · 当前方案' : '否' }}</span></td><td>{{ supplyBaseName }}</td></tr></tbody></table><div v-else class="empty-hint"><b>暂无水源数据</b>切换环境模式或刷新环境后显示。</div></section>
        </div>
      </section>

      <section v-else-if="activeTab === 'map'" class="detail-view map-view map-view-full screen"><div class="map-toolbar"><div class="map-toolbar-heading"><h2>态势总览</h2><span class="scr-hint" v-if="mission && mission.active"><i class="live-dot"></i> 自动推演中 · 第 {{ Math.min(Math.floor(missionNow / 5) + 1, activeRounds.length + 1) }} 轮 · 每轮 5 仿真分钟</span></div><div class="map-toolbar-tools"><span class="view-toggle"><button :class="['legend-item', { on: mapMode === '2d' }]" :aria-pressed="mapMode === '2d'" @click.stop="toggleMapMode('2d')">🗺 平面</button><button :class="['legend-item', { on: mapMode === '3d' }]" :aria-pressed="mapMode === '3d'" @click.stop="toggleMapMode('3d')">🏔 三维</button></span><div class="map-legend" role="group" aria-label="图层开关"><button v-for="(label, key) in LAYER_LABELS" :key="key" :class="['legend-item', { off: !layerVisibility[key] }]" :aria-pressed="layerVisibility[key]" @click.stop="toggleLayer(key)"><i :class="'legend-' + key"></i>{{ label }}</button></div><button :class="['legend-item', { on: pickMode }]" :aria-pressed="pickMode" title="开启后在地图点击指定火情位置（模拟发现火情），上传影像即以该坐标为火点" @click.stop="pickMode = !pickMode"><i class="legend-fire"></i>指定火点</button><button :class="['legend-item', { off: !voiceOn }]" :aria-pressed="voiceOn" :title="voiceOn ? '疏散语音广播已开启（点击静音）' : '疏散语音广播已静音（点击开启）'" @click.stop="toggleVoice"><i class="legend-evac"></i>语音广播</button><span class="status-tag orange"><MapPinned :size="14" /> {{ environmentCoordinates.longitude.toFixed(6) }}°E · {{ environmentCoordinates.latitude.toFixed(6) }}°N</span></div></div>
      <div class="map-screen-body"><div class="map-main-col"><div class="tactical-map-wrap" @click="dismissMarker">
        <Terrain3D v-if="mapMode === '3d'" :grid="terrainGrid" :contours="contourData" :road-context="environment?.road_context || null" :fire-gps="fire3dGps" :fire-radius-m="fire3dRadius" :fire-active="fire3dActive" :drones="drones" :mission="mission" :fire-origin="(analysisResult && analysisResult.scene ? analysisResult.scene.fire_origin : null)" :stations="stations3d" :evac-path="evac3dPath" :people-status="peopleStatus" />
        <TacticalMap v-else-if="amapReady && mapMode === '2d'" ref="tacticalMapRef" :result="result" :environment="environment" :drones="drones" :water-list="waterSourcesList" :contours="contourData" :layer-visibility="layerVisibility" :selected-uavs="(analysisResult?.dispatch_plan?.selected_uavs || [])" :mission="mission" :scenario-preview="scenarioPreview" :focus-pulse="focusPulse" :hovered-drone-id="hoveredDroneId" :hovered-water-id="hoveredWaterId" :active-marker-id="activeMarker?.id || ''" :default-center="environmentCoordinates" :pick-mode="pickMode" @select-marker="selectMarker" @coords="cursorCoords = $event" @pick-coords="applyPickedCoords" @ready="addLog('高德卫星底图加载完成')" @fallback="onAmapFallback" />
        <div v-else-if="mapMode === '2d'" class="large-map" @wheel.prevent="handleMapWheel" @pointerdown="startMapDrag" @pointermove="moveMap" @pointerup="stopMapDrag" @pointercancel="stopMapDrag" @pointerleave="stopMapDrag">
        <div class="map-scene-layer" :class="{ dragging: mapDragging }" :style="mapLayerStyle"><div class="terrain-wash"></div><div class="map-grid"></div><svg class="terrain-svg" viewBox="0 0 1000 520" preserveAspectRatio="none" aria-label="紫金山局部相对俯视等高线示意图"><defs><pattern id="topoGrid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M 40 0 L 0 0 0 40" fill="none" stroke="#b7a9a0" stroke-width=".6" opacity=".42"/></pattern></defs><rect width="1000" height="520" fill="url(#topoGrid)"/><g v-if="layerVisibility.road" class="svg-roads"><path v-for="road in svgRoadPaths" :key="road.wayId" :class="['svg-road', 'rl-' + road.cls]" :d="road.d"/></g><g v-if="layerVisibility.contour" class="contours"><g v-for="line in contourPaths" :key="line.d"><path class="contour-line" :class="{ 'major-contour': line.major }" :d="line.d"/><text v-if="line.major && line.elevation != null" class="contour-label" :x="line.labelX" :y="line.labelY">{{ line.elevation }} m</text></g></g><circle class="summit-ring" cx="560" cy="248" r="16"/><text class="summit-label" x="560" y="244" text-anchor="middle">峰顶</text><text class="summit-elevation" x="560" y="258" text-anchor="middle">{{ terrainVisual.elevation }} m</text></svg><div class="terrain-caption"><strong>紫金山 · 局部地形态势</strong><span>SRTM DEM 实测等高线 · 标注实际位置</span></div><div class="contour-note"><span>等高距</span><b>{{ contourData?.interval_m ?? terrainVisual.contourStep }} m</b><small>{{ contourData?.source || '合成等高线' }}</small></div><div class="water-panel" aria-label="水源标注清单"><div class="water-panel-head"><b>水源标注</b><small>{{ waterSourcesList.length }} 处 · 按距离排序</small></div><div v-for="(water, index) in waterSourcesList.slice(0, 5)" :key="water.id" :class="['water-row', { preferred: water.preferred, linked: hoveredWaterId === water.id }]" @mouseenter="hoveredWaterId = water.id" @mouseleave="hoveredWaterId = ''" @click="water.position && selectMarker({ id: water.id, type: 'water', x: water.position.x, y: water.position.y })" :title="'点击查看水源详情'"><i class="water-dot" :class="'wt-' + waterTypeClass(water.type)"></i><b>{{ water.preferred ? '★ ' : '' }}{{ water.name }}</b><span>{{ water.type }} · {{ water.distance != null ? water.distance + 'm' : '距离未知' }}</span><small v-if="water.coordinates">{{ water.coordinates.longitude.toFixed(6) }}°E, {{ water.coordinates.latitude.toFixed(6) }}°N</small><small v-else>相对坐标</small></div><div v-if="!waterSourcesList.length" class="water-row"><span>当前环境无水源数据（可切换环境模式后刷新）</span></div></div><div v-if="fireZone && layerVisibility.fire" class="fire-zone-ring" :style="{ left: fireZone.x, top: fireZone.y, width: fireZone.size }" :title="`火情等效范围 ${Math.round(Math.sqrt(Math.PI * (analysisResult?.fire_assessment?.fire_area_m2 || 0)))}m`"><span class="fire-zone-label">火区 ≈ {{ formatNumber(analysisResult?.fire_assessment?.fire_area_m2 || 0) }} m²</span></div><svg v-if="evacuationOverlay && layerVisibility.evacuation" class="evacuation-overlay" viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="疏散路线"><polyline :points="evacuationOverlay.points" class="evacuation-line"/></svg><div v-if="evacuationOverlay && layerVisibility.evacuation" class="map-node evacuation-exit" :style="{ left: evacuationOverlay.exit.x, top: evacuationOverlay.exit.y }"><span>出口 · 约 {{ evacuationOverlay.minutes }} 分钟</span></div><div v-for="marker in mapMarkers" :key="marker.id" :class="['map-node', marker.type, marker.waterType ? 'wt-' + waterTypeClass(marker.waterType) : '', { 'map-node-preferred': marker.preferred, 'map-node-active': activeMarker && activeMarker.id === marker.id, 'map-node-hover': hoveredDroneId === marker.id || hoveredWaterId === marker.id, 'map-node-pulse': focusPulse === marker.id }]" :style="{ left: marker.x, top: marker.y }" :title="marker.title || marker.label" @click.stop="selectMarker(marker)"><svg v-if="marker.type === 'drone'" class="node-quad" viewBox="0 0 40 40" :style="{ color: SUBGROUP_COLORS[marker.sub] || '#2563eb' }"><circle class="nq-track" cx="20" cy="20" r="15.5"/><circle class="nq-arc" cx="20" cy="20" r="15.5" transform="rotate(-90 20 20)" :stroke-dasharray="quadDash(marker.soc)"/><path class="nq-arms" d="M13 13 L27 27 M27 13 L13 27"/><circle class="nq-body" cx="20" cy="20" r="5"/></svg><component v-else :is="marker.icon" :size="17" :fill="marker.type === 'fire' ? 'currentColor' : undefined" /><span>{{ marker.label }}</span></div>

        <div class="map-compass">N</div>
        <div class="map-controls" role="group" aria-label="地图缩放控制"><button type="button" title="放大地图" aria-label="放大地图" @click="zoomMap(0.2)">+</button><button type="button" title="缩小地图" aria-label="缩小地图" @click="zoomMap(-0.2)">−</button><button type="button" title="重置地图视图" aria-label="重置地图视图" @click="resetMapView"><RefreshCw :size="14" /></button><output aria-live="polite">{{ Math.round(mapZoom * 100) }}%</output></div>
        <div class="map-scale" aria-label="比例尺"><i :style="{ width: mapScale.width }"></i><b>{{ mapScale.label }}</b></div>
      </div>
      </div>
        <div v-if="analysisResult && analysisResult.fire_assessment" :class="['fire-status-card', 'lvb-' + fireLevelNum]" role="status" aria-label="火情等级浮层">
          <div class="fsc-head"><span class="fsc-flame"><Flame :size="14" /></span><b>{{ result.fire_assessment.label }}</b><i>{{ fireLevelWord }}</i></div>
          <div class="fsc-rows">
            <span>报警时间<b>{{ (analysisEnvelope?.created_at || '').slice(0, 19).replace('T', ' ') || '—' }}</b></span>
            <span>过火面积<b>{{ formatNumber(result.fire_assessment.fire_area_m2) }} m²</b></span>
            <span>当前 FLP<b>{{ formatNumber(fireFlpNow) }}</b></span>
            <span>火点位置<b>{{ fireGpsLabel }}</b></span>
            <span>人员状态<b>{{ { confirmed: '有人在场', absent: '无人员受威胁', unknown: '情况不明' }[peopleStatus] || '—' }}</b></span>
            <span>处置结论<b>{{ controlVerdictView.hint }}</b></span>
            <span v-if="fireTrendText" :class="['fsc-trend', fireTrendText.down ? 'down' : 'up']">{{ fireTrendText.text }}<b>{{ fireTrendText.detail }}</b></span>
          </div>
        </div>
      <div v-if="activeMarker" class="marker-detail" :style="activeMarker.style" role="dialog" :aria-label="activeMarker.title">
<div class="marker-detail-head"><b>{{ activeMarker.title }}</b><button class="marker-detail-close" aria-label="关闭详情" @click.stop="activeMarker = null">×</button></div>
<div class="marker-detail-body"><div v-for="row in activeMarker.rows" :key="row.k" class="marker-detail-row"><span>{{ row.k }}</span><b>{{ row.v }}</b></div></div>
</div>
      <div v-if="amapReady && mapMode === '2d'" class="map-coords" aria-live="polite" aria-label="光标经纬度"><Crosshair :size="13" /> <template v-if="cursorCoords">{{ cursorCoords.longitude.toFixed(6) }}°E · {{ cursorCoords.latitude.toFixed(6) }}°N</template><template v-else>移动鼠标读取经纬度</template></div>
      <div v-if="windArrowDeg != null" class="map-wind-indicator" aria-label="风向指示">
        <svg viewBox="0 0 24 24" :style="{ transform: `rotate(${windArrowDeg}deg)` }"><path d="M12 2 L18 12 L14 12 L14 22 L10 22 L10 12 L6 12 Z" /></svg>
        <span>风向 · {{ result.environment.wind_direction }}风</span>
      </div>
      </div>
      </div>
      <aside class="map-side-rail" aria-label="态势信息栏">
        <div class="live-feed-card" aria-label="实时画面">
          <div class="lf-head"><b>实时画面</b><span v-if="previewUrl" class="lf-live" title="侦察回传最新帧"><i></i>LIVE</span><small v-else><span class="live-dot"></span>待接入</small><button v-if="previewUrl" class="lf-expand" title="进入火情监测查看检测详情" aria-label="进入火情监测" @click="selectNav('command')"><ExternalLink :size="13" /></button></div>
          <img v-if="previewUrl" :src="previewUrl" alt="现场影像帧">
          <div v-else class="lf-empty"><MonitorUp :size="18" /><span>等待影像接入</span><small>上传影像或开始演训后显示现场画面</small></div>
          <div v-if="liveFeedMeta" class="lf-yolo" title="YOLO 视觉观察 · 只陈述所见"><b>YOLO 已识别</b><span class="lf-fire">火焰 {{ liveFeedMeta.fire ? `${liveFeedMeta.fireConf}%` : '未检出' }}</span><span class="lf-smoke">烟雾 {{ liveFeedMeta.smoke ? `${liveFeedMeta.smokeConf}%` : '未检出' }}</span></div>
          <div class="lf-foot">
            <div v-if="frameStrip.length > 1" class="lf-thumbs" aria-label="最近帧序列"><img v-for="(frame, i) in frameStrip.slice(-2)" :key="frame.url + i" :src="frame.url" :alt="frame.label" :title="frame.label"></div>
            <span class="lf-src">源：无人机 {{ liveFeedMeta?.uav || 'R1' }} · {{ stageCapturedAt || '—' }}</span>
          </div>
          <button v-if="previewUrl" class="text-btn lf-go" @click="selectNav('command')">进入火情监测 <ChevronRight :size="14" /></button>
        </div>
        <div class="fleet-mini" aria-label="任务执行">
          <div class="fm-head"><b>任务执行</b><small>{{ missionDonut.active }}/{{ missionDonut.total }} 架出动</small></div>
          <div class="fm-donut-row">
            <div class="fm-donut">
              <svg viewBox="0 0 84 84" role="img" aria-label="机群出动占比">
                <circle class="fmd-track" cx="42" cy="42" r="34"></circle>
                <circle class="fmd-arc" cx="42" cy="42" r="34" :stroke-dasharray="missionDonut.dash"></circle>
              </svg>
              <div class="fmd-center"><b>{{ missionDonut.active }}/{{ missionDonut.total }}</b><span>已出动</span></div>
            </div>
            <div class="fm-subgroups">
              <div v-for="group in subgroupCounts" :key="group.key" class="fm-sub"><i :style="{ background: SUBGROUP_COLORS[group.key] || '#8fa39a' }"></i><span>{{ group.label }}</span><b>{{ group.active }}/{{ group.total }}</b></div>
              <div class="fm-progress"><small>任务总体进度</small><div class="fm-bar"><i :style="{ width: missionDonut.pct + '%' }"></i></div><b>{{ missionDonut.pct }}%</b></div>
            </div>
          </div>
          <div class="fm-stage-row"><span>当前阶段</span><b class="fm-stage-chip">{{ overviewStageLabel }}</b></div>
          <div class="fm-stage-row"><span>下次评估</span><b>{{ mission?.active ? `${Math.floor(missionNow % 5)}/5 min` : (taskStatus === '执行中' ? '可手动执行' : '—') }}</b></div>
        </div>
        <div class="rail-terrain env-panel-card">
          <div class="fm-head"><b>环境与趋势</b><small>{{ environmentSource }}</small></div>
          <div class="env-rows">
            <span v-for="row in envPanelRows" :key="row.label" class="env-row"><i>{{ row.label }}</i><b>{{ row.value }}</b></span>
          </div>
          <div class="env-foot"><Wind :size="15" /><span>{{ result.environment.wind_direction || '—' }}风 · {{ result.environment.wind_speed ?? '—' }} m/s · 海拔 {{ terrainVisual.elevation }} m</span></div>
          <EvolutionChart :rounds="activeRounds" />
        </div>
        <div class="water-panel" aria-label="水源标注清单"><div class="water-panel-head"><b>水源标注</b><small>{{ waterSourcesList.length }} 处 · 按距离排序</small></div><div v-for="(water, index) in waterSourcesList.slice(0, 8)" :key="water.id" :class="['water-row', { preferred: water.preferred, linked: hoveredWaterId === water.id }]" @mouseenter="hoveredWaterId = water.id" @mouseleave="hoveredWaterId = ''" @click="onWaterRowClick(water)" :title="'点击查看水源详情'"><i class="water-dot" :class="'wt-' + waterTypeClass(water.type)"></i><b>{{ water.preferred ? '★ ' : '' }}{{ water.name }}</b><span>{{ water.type }} · {{ water.distance != null ? water.distance + 'm' : '距离未知' }}</span><small v-if="water.coordinates">{{ water.coordinates.longitude.toFixed(6) }}°E, {{ water.coordinates.latitude.toFixed(6) }}°N</small><small v-else>相对坐标</small></div><div v-if="!waterSourcesList.length" class="water-row"><span>当前环境无水源数据（可切换环境模式后刷新）</span></div></div>
      </aside></div>
      <div class="map-statusbar"><template v-if="analysisResult"><span class="plan-slice">当前方案 <b>方案 {{ planVersionLabel || 'V1' }}</b></span><span class="plan-slice">预计控制 <b>{{ controlWindow }}</b></span><span class="plan-slice">当前结论 <b>{{ controlVerdictView.hint }}</b></span><span class="plan-slice">下次评估 <b>{{ mission?.active ? `第 ${Math.min(Math.floor(missionNow / 5) + 1, activeRounds.length + 1)} 轮` : (taskStatus === '执行中' ? '可手动执行' : '—') }}</b></span><button class="plan-open" @click="reportViewer.open = true"><FileText :size="13" /> 查看详细方案</button></template><template v-else><span class="plan-slice">当前任务 <b>{{ scenario ? '演训火情已生成 · 到「火情监测」开始模拟' : '待命 · 到「火情监测」上传影像或生成演训火情' }}</b></span></template><span class="map-source map-meta" :class="{ fallback: !contourData }" :title="`等高距 ${contourData?.interval_m ?? terrainVisual.contourStep} m`">{{ contourLoading ? '等高线加载中' : `等高线 · ${contourData?.source || '合成回退'}` }}</span><span class="map-meta">火点基准 {{ fireGpsLabel || '—' }}</span></div></section>

      <section v-else-if="activeTab === 'analysis'" class="detail-view">
        <div class="detail-heading"><div><h2>数据分析</h2><p>当前任务复盘指标 · 前后轮次对比 · 多任务对比 · 回放与报告输出。</p></div><span class="status-tag" :class="analysisId ? '' : 'orange'"><span :class="['live-dot', { offline: !analysisId }]"></span>{{ analysisId ? `当前任务 ${analysisId.slice(-8)}` : '暂无进行中任务' }}</span></div>
        <div class="analysis-grid">
          <div class="ana-col">
            <section class="panel"><div class="panel-heading"><h2>当前任务分析</h2><span class="log-count">指标出自轮次账本 · 无独立口径</span></div>
              <div class="ana-stats">
                <div class="ana-stat"><small>FLP 变化</small><b :class="anaStats.changeDown ? 'down' : (anaStats.changePct !== '—' ? 'up' : '')">{{ anaStats.changePct }}</b><em>较初始</em></div>
                <div class="ana-stat"><small>自然增长</small><b class="up">{{ anaStats.growth }}</b><em>FLP · 最新轮</em></div>
                <div class="ana-stat"><small>有效压制</small><b class="down">{{ anaStats.supp }}</b><em>FLP · 最新轮</em></div>
                <div class="ana-stat"><small>净变化</small><b :class="anaStats.netDown ? 'down' : (anaStats.net !== '—' ? 'up' : '')">{{ anaStats.net }}</b><em>压制效率 {{ anaStats.eff }}</em></div>
              </div>
              <div class="ana-charts">
                <AreaTrendChart :rounds="activeRounds" :area-per-flp="result?.fire_assessment?.area_per_flp || 0" />
                <EvolutionChart :rounds="activeRounds" />
              </div>
              <template v-if="activeRounds.length">
                <div class="ana-subhead">资源消耗</div>
                <div class="ana-kpis ana-kpis-5">
                  <div v-for="card in anaResourceCards" :key="card.label" class="ana-stat kpi"><small>{{ card.label }}</small><b>{{ card.value }}<i>{{ card.unit }}</i></b></div>
                </div>
                <div class="ana-secondary">
                  <div v-for="card in anaSecondaryCards" :key="card.label" class="ana-stat secondary"><small>{{ card.label }}</small><b>{{ card.value }}</b><em>{{ card.unit }}</em></div>
                </div>
              </template>
              <div v-else class="empty-hint"><b>暂无轮次数据</b>完成一次研判并批准方案推演后，这里会给出复盘指标。</div>
            </section>
          </div>
          <div class="ana-col">
            <section class="panel"><div class="panel-heading"><h2>多任务对比</h2><span class="log-count">勾选 2–4 个任务横向对比</span></div>
              <div class="ana-pick">
                <div v-if="historyLoading" class="skeleton-row"></div>
                <div v-else-if="!historyTasks.length" class="empty-hint"><b>还没有历史任务</b>完成任务研判后可在这里勾选对比。</div>
                <label v-for="task in historyTasks.slice(0, 12)" :key="task.analysis_id"><input type="checkbox" :value="task.analysis_id" v-model="anaCompareSel"><span>{{ task.analysis_id }}</span><small style="margin-left:auto;color:var(--ink-3)">{{ (task.created_at || '').slice(5, 16).replace('T', ' ') }}</small></label>
              </div>
              <ComparePanel v-if="anaCompareOpen" :ids="anaCompareSel" layout="rows" @error="errorMessage = $event" />
            </section>
          </div>
        </div>

            <section class="panel" v-if="roundsTable.length"><div class="panel-heading"><h2>前后轮次对比</h2><span class="log-count">共 {{ roundsTable.length }} 轮 · 每轮 5 仿真分钟</span></div><div class="gt-scroll ana-rounds-scroll"><table class="data-table"><thead><tr><th>轮次</th><th class="num">轮前 FLP</th><th class="num">自然增长</th><th class="num">有效压制</th><th class="num">轮后 FLP</th><th class="num">工作机</th><th class="num">返航机</th><th class="num">补给机</th><th class="num">水剂 L</th><th class="num">CO₂ kg</th><th>库存变化</th></tr></thead><tbody><tr v-for="row in roundsTable" :key="row.no"><td class="num"><b>#{{ row.no }}</b><span v-if="row.replan" class="dt-chip orange" style="margin-left:6px">重规划</span></td><td class="num">{{ formatNumber(row.before) }}</td><td class="num ana-up">{{ row.growth != null ? '+' + formatNumber(row.growth) : '—' }}</td><td class="num ana-down">{{ row.supp != null ? formatNumber(row.supp) : '—' }}</td><td class="num">{{ formatNumber(row.after) }}</td><td class="num">{{ row.working || '—' }}</td><td class="num">{{ row.returning || '—' }}</td><td class="num">{{ row.supplying || '—' }}</td><td class="num">{{ row.water != null ? formatNumber(row.water) : '—' }}</td><td class="num">{{ row.co2 != null ? formatNumber(row.co2) : '—' }}</td><td class="ana-stock">{{ row.stock }}</td></tr></tbody></table></div></section>
        <div class="ana-bottom">
          <div class="ana-bottom-left">
            <ReplayPanel v-if="activeRounds.length" :rounds="activeRounds" :area-per-flp="result?.fire_assessment?.area_per_flp || 0" :fire-origin="analysisResult?.scene?.fire_origin || null" default-open />
            <section v-else class="panel"><div class="panel-heading"><h2>复盘回放</h2></div><div class="empty-hint"><b>暂无可回放轮次</b>批准方案并推演后可在此逐轮回放。</div></section>
          </div>
          <section class="panel"><div class="panel-heading"><h2>报告输出</h2><span class="log-count">复盘产物 · 一键导出</span></div>
            <div class="report-output">
              <button class="report-out-btn" :disabled="!analysisId" @click="reportViewer.open = true"><span class="ro-icon"><FileText :size="17" /></span><span>在线查看报告<small>生成可视化分析报告</small></span></button>
              <a class="report-out-btn" :class="{ disabled: !analysisId }" :href="analysisId ? `/api/tasks/${analysisId}/report/export` : undefined" :download="analysisId ? '图文报告.html' : undefined" @click="!analysisId && $event.preventDefault()"><span class="ro-icon"><FileDown :size="17" /></span><span>导出图文报告<small>独立 HTML · 可打印为 PDF</small></span></a>
              <a class="report-out-btn" :class="{ disabled: !analysisId }" :href="analysisId ? `/api/tasks/${analysisId}/report` : undefined" :download="analysisId ? '任务数据.json' : undefined" @click="!analysisId && $event.preventDefault()"><span class="ro-icon"><Database :size="17" /></span><span>导出任务数据<small>JSON 原始档案</small></span></a>
              <a class="report-out-btn" :class="{ disabled: !analysisId }" :href="analysisId ? `/api/tasks/${analysisId}/report/export` : undefined" target="_blank" rel="noopener" @click="!analysisId && $event.preventDefault()"><span class="ro-icon"><ClipboardList :size="17" /></span><span>生成 PDF 材料<small>浏览器打印一键成 PDF</small></span></a>
            </div>
            <ReportViewer v-if="reportViewer.open" :analysis-id="analysisId" :verdict-report="controlVerdictView.report" @error="errorMessage = $event" />
          </section>
        </div>
      </section>

      <HistoryPanel v-else-if="activeTab === 'history'" :tasks="historyTasks" :loading="historyLoading" @restore="selectHistoryTask" @refresh="loadHistory" @error="errorMessage = $event" />

      <section v-else class="detail-view"><div class="detail-heading"><div><h2>任务日志</h2><p>记录当前演示任务的输入、分析阶段和调度决策。</p></div><span class="status-tag"><Activity :size="14" /> {{ logs.length }} 条记录</span></div><div class="full-logs"><div v-for="(log, index) in foldedLogs" :key="log.message + log.timestamp + index"><span class="log-time">{{ logTime(log, index) }}</span><i :class="{ bright: index === 0 }"></i><span>{{ logText(log) }}</span><small v-if="typeof log === 'object'" class="log-meta">{{ log.stage }} · {{ log.source }}</small><b v-if="log.repeat > 1" class="log-repeat">×{{ log.repeat }}</b><small>{{ index === 0 ? 'LATEST' : 'EVENT' }}</small></div></div></section>
    </main>
  </div>
</template>
