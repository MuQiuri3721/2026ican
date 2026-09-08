<script setup>
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import TacticalMap from './components/TacticalMap.vue'
import ChatPanel from './components/ChatPanel.vue'
const Terrain3D = defineAsyncComponent(() => import('./components/Terrain3D.vue'))
import PhaseStepper from './components/PhaseStepper.vue'
import EvolutionChart from './components/EvolutionChart.vue'
import {
  Activity,
  Bell,
  Bot,
  ChevronRight,
  CloudRain,
  Crosshair,
  Droplets,
  FileImage,
  Flame,
  Gauge,
  ListFilter,
  Map,
  MapPinned,
  Radio,
  RefreshCw,
  ShieldCheck,
  Upload,
  Wind,
  Zap,
} from 'lucide-vue-next'

const activeTab = ref('command')
const viewTab = ref('overview')
const analyzing = ref(false)
const monitoring = ref(false)
const uploaded = ref(false)
const selectedFile = ref(null)
const previewUrl = ref('')
const fileInput = ref(null)
const progress = ref(0)
const errorMessage = ref('')
const analysisEnvelope = ref(null)
const analysisResult = ref(null)
const analysisId = ref('')
const environment = ref(null)
const fleet = ref([])
const inventory = ref(null)
const peopleStatus = ref('unknown')
const useVlm = ref(false)
const maxDrones = ref(4)
const targetMinutes = ref(null)
const disabledUavs = ref([])
// BE-13（评审问题1 · 2+6+4 扩容接通）：可灭火机 = 灭火单元 E1-E6 + multi_role 支援机
// S3/S4（共 8 架，S3/S4 计入灭火出动上限）。出动上限选项与禁用名单全部从 /api/fleet
// 动态生成，不再写死 1–4 与 E1–E4；机群接口不可用时回退 4 选项演示口径。
const fightingUavIds = computed(() => drones.value.filter((d) => d.role === 'firefighting' || d.multi_role).map((d) => d.id))
const maxDronesOptions = computed(() => Math.max(fightingUavIds.value.length, 4))
const disableOptions = computed(() => (fightingUavIds.value.length ? fightingUavIds.value : ['E1', 'E2', 'E3', 'E4']))
const reasonInput = ref('')
const reportViewer = ref({ open: false, loading: false, data: null })
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
function deployRowClass(drone) {
  return {
    selected: drone.selected,
    linked: hoveredDroneId.value === drone.id || Boolean(activeMarker.value && activeMarker.value.id === drone.id),
  }
}

const focusPulse = ref('')
function focusDeployment(drone) {
  if (!layerVisibility.value.drone) { errorMessage.value = '无人机图层已隐藏，请先在图例中打开。'; return }
  // 真实地图模式下直接在卫星图上脉冲定位，示意图模式沿用标记脉冲
  if (amapReady.value && tacticalMapRef.value) { tacticalMapRef.value.pulseMarker(drone.id); return }
  // 点击部署行 → 地图标记脉冲定位两秒（行内已含全部信息，详情在地图标记点击查看）
  focusPulse.value = drone.id
  setTimeout(() => { if (focusPulse.value === drone.id) focusPulse.value = '' }, 2000)
}

// —— 真实卫星地图（高德）：Key 缺失或加载失败时回退等高线示意图 ——
const tacticalMapRef = ref(null)
const amapRuntimeFailed = ref(false)
const cursorCoords = ref(null)
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
const environmentLoading = ref(false)
const environmentMode = ref('real')
const environmentCoordinates = ref({ latitude: 32.0725, longitude: 118.8415 })
const coordinateDraft = ref({ ...environmentCoordinates.value })
const coordinateError = ref('')
const environmentRequestToken = ref(0)
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
const logs = ref([
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

const drones = ref([
  { id: 'R1', label: '侦察单元', role: 'reconnaissance', subgroup: 'reconnaissance', battery: 92, soc: 92, status: '待命', module: 'EO/IR', payload: '—', signal: 96, health: 100, color: 'blue', task: '待命' },
  { id: 'R2', label: '侦察单元', role: 'reconnaissance', subgroup: 'reconnaissance', battery: 88, soc: 88, status: '待命', module: 'EO/IR', payload: '—', signal: 94, health: 98, color: 'blue', task: '待命' },
  { id: 'E1', label: '灭火单元', role: 'firefighting', subgroup: 'suppression', battery: 92, soc: 92, status: '待命', module: 'water_20l', payload: '20 L', signal: 90, health: 100, color: 'orange', task: '待命' },
  { id: 'E2', label: '灭火单元', role: 'firefighting', subgroup: 'suppression', battery: 86, soc: 86, status: '待命', module: 'water_20l', payload: '20 L', signal: 88, health: 100, color: 'orange', task: '待命' },
  { id: 'E3', label: '灭火单元', role: 'firefighting', subgroup: 'suppression', battery: 79, soc: 79, status: '待命', module: 'co2_6kg', payload: '6 kg', signal: 86, health: 97, color: 'orange', task: '待命' },
  { id: 'E4', label: '灭火单元', role: 'firefighting', subgroup: 'suppression', battery: 74, soc: 74, status: '待命', module: 'water_20l', payload: '20 L', signal: 84, health: 96, color: 'orange', task: '待命' },
  { id: 'S1', label: '支援单元', role: 'support', subgroup: 'support', battery: 95, soc: 95, status: '待命', module: 'sup_10', payload: '10 kg', signal: 98, health: 100, color: 'green', task: '待命' },
  { id: 'S2', label: '支援单元', role: 'support', subgroup: 'support', battery: 90, soc: 90, status: '待命', module: 'sup_10', payload: '10 kg', signal: 95, health: 99, color: 'green', task: '待命' },
])

const FLEET_GROUP_META = [
  { key: 'reconnaissance', label: '侦察单元', role: '火情侦察与态势回传' },
  { key: 'suppression', label: '灭火单元', role: '主力灭火 · 水剂 / 干粉模块' },
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
    estimated_control_time: { earliest_minutes: 12, latest_minutes: 17, window_minutes: [12, 17], unit: 'min', simulated: false },
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
const statusLabels = { succeeded: '已完成', completed: '已完成', running: '执行中', awaiting_confirmation: '待确认', approved: '已批准', executing: '执行中', replanning: '重规划中', terminated: '已终止', action_required: '需要处置', failed: '失败', queued: '排队中', available: '待命', assigned: '已分配', flying: '飞行中', working: '作业中', returning: '返航中', servicing: '维护中', charging: '充电中', fault: '故障', offline: '离线' }
const AGENT_MSG_LABELS = { TASK_ASSIGN: '建案派任务', FINDING: '态势发现', PLAN_PROPOSAL: '方案提案', SIM_RESULT: '仿真评估', APPROVAL_REQ: '审批请求', APPROVAL_DECISION: '审批仲裁', JUDGMENT: '自主研判', REPLAN_TRIGGER: '重规划触发', REPORT: '结案报告', EVAC_BROADCAST: '疏散广播', UAV_FAULT: '单机失能', BACKFILL: '补位接替', RECOVERY: '结案回收', INFO: '信息', ERROR: '异常' }
const AGENT_SOURCE_LABELS = { glm: 'GLM 在线', 'conservative-fallback': '保守降级', 'deterministic-offline': '规则离线', rules: '规则引擎', agent: 'Agent', user: '指挥员', 'parse-failed': '解析回退' }
function agentMsgLabel(type) { return AGENT_MSG_LABELS[type] || type }
function agentSourceLabel(source) { return AGENT_SOURCE_LABELS[source] || source || '规则' }
const displayStatus = computed(() => statusLabels[analysisEnvelope.value?.status] || analysisEnvelope.value?.status || taskStatus.value)
const plan = computed(() => result.value.dispatch_plan || {})
const planStatus = computed(() => analysisEnvelope.value?.status || (plan.value.feasibility === false ? 'awaiting_confirmation' : 'ready'))
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
const latestRound = computed(() => activeRounds.value.at(-1))
const monitorArea = computed(() => monitorResult.value?.next_fire_area_m2 ?? result.value.fire_assessment.fire_area_m2)
const dataMode = computed(() => result.value.data_mode || '本地演示数据 · 规则引擎')
// VLM 视觉解释（E-2 开发侧就绪）：vlm_explanation 由后端三级来源生成（vlm 直连 / 适配器 / 规则回退），来源随行标注
const foldedLogs = computed(() => {
  const folded = []
  for (const log of logs.value) {
    const last = folded[folded.length - 1]
    if (last && last.stage === log.stage && last.source === log.source && last.message === log.message) {
      last.repeat = (last.repeat || 1) + 1
      continue
    }
    folded.push({ ...log, repeat: 1 })
  }
  return folded
})
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
const issueText = (item) => {
  if (item == null) return ''
  if (typeof item === 'string') return item
  if (typeof item === 'object') return item.message || item.description || item.reason || ''
  return String(item)
}
const vlmNoteBody = computed(() => {
  const note = vlmNote.value
  if (!note) return ''
  return note.human_summary || note.summary || ''
})
const vlmNoteSource = computed(() => {
  const note = vlmNote.value
  if (!note) return ''
  const bits = [note.mode === 'real' ? (note.source || 'vlm') : (note.source || 'rule-explainer-fallback')]
  if (note.prompt_version) bits.push(`提示词 ${note.prompt_version}`)
  if (note.adapter_fallback?.code) bits.push(`回退 ${note.adapter_fallback.code}`)
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
  return `路线 ${eva.steps} 步 · 约 ${eva.estimated_minutes} 分钟 · 避开 ${eva.risk_cells} 个风险格`
})
// —— 疏散语音广播（FE-21，范式参考 firepatrol TTS）：有人分支路线生成即口播，可一键静音 ——
const voiceOn = ref(true)
const spokenEvacFor = ref('')
watch(() => analysisResult.value && analysisResult.value.agent && analysisResult.value.agent.skill_chain
  ? analysisResult.value.agent.skill_chain.evacuation : null, (eva) => {
  if (!voiceOn.value || !eva || !eva.found || !analysisId.value || spokenEvacFor.value === analysisId.value) return
  spokenEvacFor.value = analysisId.value
  speakText(`人员区域请注意:现场发现火情,请立即沿疏散路线向出口撤离,全程约 ${eva.estimated_minutes} 分钟,共 ${eva.steps} 段路线,避开 ${eva.risk_cells} 个风险格,救援无人机将在上空引导。`)
})
const TTS_VOICE = 'zh-CN-XiaoxiaoNeural' // Edge TTS 神经音色（晓晓）；失败回落浏览器 TTS
let edgeAudio = null
function speakText(text) {
  // 优先 Edge TTS 神经音色（FE-36）：后端合成 mp3；外网波动/未安装时回落浏览器 speechSynthesis
  fetch(`/api/tts?text=${encodeURIComponent(text.slice(0, 300))}&voice=${TTS_VOICE}`)
    .then((response) => {
      if (!response.ok) throw new Error(`tts ${response.status}`)
      return response.blob()
    })
    .then((blob) => {
      if (edgeAudio) { edgeAudio.pause(); edgeAudio = null }
      edgeAudio = new Audio(URL.createObjectURL(blob))
      edgeAudio.play().catch(() => speakBrowserTts(text))
    })
    .catch(() => speakBrowserTts(text))
}
function speakBrowserTts(text) {
  try {
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = 'zh-CN'
    utterance.rate = 1.05
    window.speechSynthesis.cancel()
    window.speechSynthesis.speak(utterance)
  } catch (error) { console.warn(error) }
}
function toggleVoice() {
  voiceOn.value = !voiceOn.value
  if (!voiceOn.value) {
    try { window.speechSynthesis.cancel() } catch (error) { /* 浏览器不支持时静默 */ }
    if (edgeAudio) { edgeAudio.pause(); edgeAudio = null }
  }
  addLog(`疏散语音广播${voiceOn.value ? '开启' : '已静音'}`)
}

const fireChange = computed(() => {
  const round = activeRounds.value.at(-1)
  const before = round?.before?.fire_load_flp
  const after = round?.after?.fire_load_flp
  if (!before || after == null) return '待监测'
  const delta = ((after - before) / before) * 100
  return `${delta > 0 ? '+' : ''}${delta.toFixed(1)}%`
})
const metrics = computed(() => [
  { label: '火焰面积', value: formatNumber(result.value.fire_assessment.fire_area_m2), unit: 'm²', change: fireChange.value, tone: 'orange', icon: Flame },
  { label: '烟雾覆盖', value: formatNumber(result.value.fire_assessment.smoke_area_m2), unit: 'm²', change: `增长率 ${Math.round((result.value.fire_assessment.growth_rate || 0) * 100)}%`, tone: 'slate', icon: CloudRain },
  { label: '风速 / 风向', value: result.value.environment.wind_speed, unit: `m/s · ${result.value.environment.wind_direction}`, change: '扩散预警', tone: 'blue', icon: Wind },
  { label: '研判置信度', value: Math.round(result.value.fire_assessment.confidence * 100), unit: '%', change: '高可信', tone: 'green', icon: ShieldCheck },
])

const navItems = [
  { id: 'command', label: '指挥中枢', icon: Crosshair },
  { id: 'fleet', label: '无人机集群', icon: Radio },
  { id: 'map', label: '林区态势', icon: Map },
  { id: 'logs', label: '任务日志', icon: Activity },
]

const environmentStatus = computed(() => environment.value?.status || '未加载')
const environmentSource = computed(() => environment.value?.source || '—')
const environmentStale = computed(() => Boolean(environment.value?.stale))
const environmentFallback = computed(() => environment.value?.fallback?.message || '')
const environmentLocation = computed(() => environment.value?.location || environmentCoordinates.value)
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

function waterTypeClass(typeText) {
  const t = String(typeText || '')
  if (t.includes('水库')) return 'reservoir'
  if (t.includes('湖')) return 'lake'
  if (t.includes('河')) return 'river'
  if (t.includes('塘')) return 'pond'
  return 'water'
}

function waterTypeLabel(water) {
  const type = String(water?.type || water?.water_type || water?.category || '').toLowerCase()
  if (type.includes('lake') || type.includes('湖')) return '湖泊'
  if (type.includes('reservoir') || type.includes('水库')) return '水库'
  if (type.includes('river') || type.includes('河')) return '河流'
  if (type.includes('pond') || type.includes('塘')) return '池塘'
  return water?.type || water?.water_type || '水源'
}

function waterLabel(water) {
  const coordinates = pointCoordinates(water)
  const distance = Number(water?.distance_m)
  const distanceText = Number.isFinite(distance) ? `${Math.round(distance)}m` : '距离未知'
  const coordinateText = coordinates ? `${coordinates.longitude.toFixed(6)}°E, ${coordinates.latitude.toFixed(6)}°N` : relativePoint(water) ? `相对 ${Math.round(relativePoint(water).x)}, ${Math.round(relativePoint(water).y)}` : '坐标缺失'
  return `${waterTypeLabel(water)} · ${water?.name || '未命名'} · ${distanceText} · ${coordinateText}`
}

const mapRoutes = computed(() => {
  const roads = environment.value?.road_context
  return roads?.routes || roads?.nodes || (roads?.nearest_transport ? [roads.nearest_transport] : [])
})
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

// —— 指挥大屏（FE-19）：阶段轨 / KPI / 事件流（范式参考 firepatrol-agents，数据全部来自现有黑板状态） ——
const SUBGROUP_COLORS = { reconnaissance: '#7fb3ff', suppression: '#e07856', support: '#5fbd92' }
const deploymentGroups = computed(() => fleetGroups.value
  .map((group) => ({ key: group.key, label: group.label, rows: deploymentList.value.filter((row) => row.subgroup === group.key) }))
  .filter((group) => group.rows.length))
const replanCount = computed(() => Math.max(0, (analysisEnvelope.value?.plan_versions?.length || 1) - 1))
const screenStage = computed(() => {
  const status = analysisEnvelope.value?.status || ''
  if (status === 'completed' || status === 'succeeded') return { stage: 7, done: true, dead: false }
  if (status === 'rejected' || status === 'terminated' || status === 'failed') return { stage: 6, done: false, dead: true }
  if (status === 'executing' || status === 'replanning' || status === 'approved' || Boolean(mission.value?.active)) return { stage: 5, done: false, dead: false }
  if (status === 'awaiting_confirmation' || status === 'action_required') return { stage: 4, done: false, dead: false }
  if (analyzing.value) {
    const p = progress.value
    return { stage: p >= 72 ? 3 : p >= 48 ? 2 : p >= 24 ? 1 : 0, done: false, dead: false }
  }
  if (analysisResult.value) return { stage: 3, done: false, dead: false }
  return { stage: uploaded.value || scenario.value ? 0 : -1, done: false, dead: false }
})
const screenKpis = computed(() => {
  const fire = result.value.fire_assessment || {}
  const env = result.value.environment || {}
  const total = drones.value.length || 8
  const active = (analysisResult.value?.dispatch_plan?.selected_uavs || []).length
  const round = activeRounds.value.at(-1)
  return [
    { label: '火焰面积', value: fire.fire_area_m2 != null ? formatNumber(fire.fire_area_m2) : '—', unit: 'm²', tone: 'ember', sub: fireChange.value },
    { label: '火情负荷', value: fire.fire_load_flp != null ? String(fire.fire_load_flp) : '—', unit: 'FLP', tone: 'danger', sub: fire.growth_rate != null ? `增长率 ${Math.round(fire.growth_rate * 100)}%` : '—' },
    { label: '现场风况', value: env.wind_speed != null ? String(env.wind_speed) : '—', unit: `m/s · ${env.wind_direction || '—'}`, tone: 'blue', sub: env.altitude != null ? `海拔 ${env.altitude} m` : '实时环境' },
    { label: '机群出动', value: String(active), unit: `/ ${total} 架`, tone: 'green', sub: `待命 ${Math.max(0, total - active)} 架` },
    { label: '监测轮次', value: String(activeRounds.value.length), unit: '轮', tone: 'slate', sub: round ? `最新 B ${round.after ? (round.after.fire_load_flp ?? round.after.flp) : '—'}` : `预计 ${controlWindow.value}` },
  ]
})
const STREAM_TYPE_META = {
  system: ['系统', '#8fa39a'], scene: ['场景', '#7fb3ff'], fleet: ['集群', '#5fbd92'], ui: ['操作', '#b9a3e0'],
  monitor: ['监测', '#f0a848'], mission: ['出动', '#e07856'], scenario: ['演训', '#e2b95d'], rules: ['规则引擎', '#5fbd92'],
  perception: ['感知', '#7fb3ff'], analysis: ['研判', '#7fb3ff'], dispatch: ['调度', '#e07856'], approval: ['审批', '#f0a848'],
}
function streamType(log) {
  const stage = typeof log === 'object' ? log.stage : ''
  const meta = STREAM_TYPE_META[stage]
  return meta ? { label: meta[0], color: meta[1] } : { label: stage || '事件', color: '#8fa39a' }
}

// 火情演化 sparkline：逐轮 after FLP
const evolution = computed(() => {
  const rounds = activeRounds.value
  if (!rounds.length) return null
  const values = rounds.map((round) => Number(round.after?.fire_load_flp ?? round.after?.flp ?? NaN)).filter((v) => Number.isFinite(v))
  if (!values.length) return null
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = Math.max(max - min, 1e-6)
  const points = values.map((value, index) => `${(index / Math.max(values.length - 1, 1)) * 100},${28 - ((value - min) / span) * 24}`).join(' ')
  return { points, single: values.length < 2, first: values[0], last: values[values.length - 1] }
})
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
const contourPaths = computed(() => {
  const features = contourData.value?.features
  if (Array.isArray(features) && features.length) {
    const coordinates = features.flatMap((feature) => {
      const geometry = feature?.geometry
      if (geometry?.type === 'LineString') return [geometry.coordinates]
      if (geometry?.type === 'MultiLineString') return geometry.coordinates || []
      return []
    }).filter((line) => line.length >= 2)
    if (coordinates.length) {
      const origin = mapProjection.value.origin
      const projected = coordinates.map((line) => line.map(([longitude, latitude]) => mapProjection.value.meters({ latitude, longitude })))
      const extent = Math.max(500, ...projected.flat().map((point) => Math.hypot(point.x, point.y)))
      return projected.map((line, index) => {
        const points = line.map(({ x, y }) => `${(500 + (x / extent) * 450).toFixed(1)} ${(260 - (y / extent) * 235).toFixed(1)}`)
        const feature = features[index]
        const elevation = Number(feature?.properties?.elevation_m ?? feature?.properties?.elevation ?? '')
        return { d: `M ${points.join(' L ')}`, elevation: Number.isFinite(elevation) ? Math.round(elevation) : null, major: index % 4 === 0, labelX: 500 + (line[0].x / extent) * 450, labelY: 260 - (line[0].y / extent) * 235 }
      })
    }
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

const environmentFeatures = computed(() => {
  const raw = environment.value?.raw?.weather?.data || environment.value?.raw?.weather || {}
  const terrain = environment.value?.terrain || {}
  const land = environment.value?.landcover || {}
  const water = environment.value?.nearest_water
  const road = environment.value?.road_context?.nearest_transport || environment.value?.road_context?.nearest_vehicle_access_candidate
  return [
    { label: '天气', value: raw.temperature_c != null ? `${raw.temperature_c}°C · 湿度 ${raw.relative_humidity_pct ?? '—'}% · 降水 ${raw.precipitation_mm ?? '—'}mm · 阵风 ${raw.wind_gust_m_s ?? '—'}m/s` : (environment.value?.wind_speed != null ? `${environment.value.wind_speed} m/s · ${environment.value.wind_direction || '—'}` : '暂无'), tone: 'blue' },
    { label: '地形', value: terrain.slope_deg != null ? `坡度 ${terrain.slope_deg}° · 上坡 ${terrain.upslope_direction || '—'} / 下坡 ${terrain.downslope_direction || '—'}` : (environment.value?.terrain || '暂无'), tone: 'green' },
    { label: '土地覆盖', value: land.burnable_ratio != null ? `${land.dominant_class || land.class_name || '—'} · 可燃 ${(land.burnable_ratio * 100).toFixed(1)}% · ${land.fuel_possible ? '可能有燃料' : '燃料较少'}` : '暂无', tone: 'green' },
    { label: '水源', value: water ? `${water.name || '未命名水源'} · ${water.distance_m ?? '—'}m · ${water.latitude ?? '—'}, ${water.longitude ?? '—'}` : '暂无', empty: !water, tone: 'blue' },
    { label: '首选水源', value: (() => { const preferred = environment.value?.preferred_water; return preferred ? `${preferred.name || '未命名'} · ${preferred.distance_m ?? '—'}m · ${waterTypeLabel(preferred)}` : (water ? `${water.name || '未命名'}（最近）` : '暂无'); })(), tone: 'blue' },
    { label: '道路', value: road ? `${road.name || '未命名道路'} · ${road.distance_m ?? '—'}m · ${road.nearest_point?.latitude ?? '—'}, ${road.nearest_point?.longitude ?? '—'}` : '暂无', empty: !road, tone: 'orange' },
  ]
})

function applyCoordinates() {
  const latitude = Number(coordinateDraft.value.latitude)
  const longitude = Number(coordinateDraft.value.longitude)
  if (!Number.isFinite(latitude) || latitude < -90 || latitude > 90 || !Number.isFinite(longitude) || longitude < -180 || longitude > 180) {
    coordinateError.value = '纬度范围 -90 至 90，经度范围 -180 至 180，且必须为数字。'
    return
  }
  coordinateError.value = ''
  environmentCoordinates.value = { latitude, longitude }
  loadEnvironment()
  loadContours()
  addLog(`火点坐标已更新 · ${latitude.toFixed(7)}, ${longitude.toFixed(7)}`)
}

async function loadEnvironment() {
  const requestToken = ++environmentRequestToken.value
  environmentLoading.value = true
  try {
    const { latitude, longitude } = environmentCoordinates.value
    const query = new URLSearchParams({ scene_id: scene.id, latitude: String(latitude), longitude: String(longitude), environment_mode: environmentMode.value, water_radius_m: '5000', road_radius_m: '5000' })
    const response = await fetch(`/api/environment?${query}`)
    if (!response.ok) throw new Error('环境接口不可用')
    const payload = await response.json()
    if (requestToken !== environmentRequestToken.value) return
    environment.value = payload
    addLog(`环境数据已刷新 · ${payload.source || 'unknown'}${payload.stale ? ' · stale' : ''}`)
  } catch (error) {
    if (requestToken === environmentRequestToken.value) addLog('环境数据刷新失败 · 保持当前状态')
    console.warn(error)
  } finally {
    if (requestToken === environmentRequestToken.value) environmentLoading.value = false
  }
}

async function loadContours() {
  const requestToken = ++contourRequestToken.value
  contourLoading.value = true
  try {
    const { latitude, longitude } = environmentCoordinates.value
    const query = new URLSearchParams({ latitude: String(latitude), longitude: String(longitude), radius_deg: '0.05', interval_m: '20', max_points: '240' })
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
  if (event.target?.closest?.('.map-node, .map-legend, .map-controls, .water-panel, .deploy-panel, .map-source, .marker-detail, .stream-panel')) return
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
const todayLabel = computed(() => {
  const now = new Date()
  return `${now.getFullYear()}.${String(now.getMonth() + 1).padStart(2, '0')}.${String(now.getDate()).padStart(2, '0')}`
})

const MODULE_LABELS = { none: '无载荷', water_20l: '水剂 20L', co2_6kg: 'CO₂ 6kg', sup_10: '补给 10kg' }
const LAYER_LABELS = { fire: '火点', water: '水源', road: '道路', drone: '无人机', contour: '等高线', evacuation: '疏散路线' }
function moduleLabel(module) {
  return MODULE_LABELS[module] || module || '—'
}

function formatNumber(value) {
  return new Intl.NumberFormat('zh-CN').format(value)
}

function selectNav(id) {
  activeTab.value = id
  if (id === 'command') viewTab.value = 'overview'
  else if (id === 'logs') viewTab.value = '' // 清除 agents/history 页签残留，否则侧边栏/铃铛进日志会命中 agents/history 分支
}

function selectView(id) {
  viewTab.value = id
  if (id === 'monitor') activeTab.value = 'map'
  else if (id === 'history') activeTab.value = 'logs'
  else if (id === 'overview') activeTab.value = 'command'
  else if (id === 'agents') activeTab.value = 'logs'
  if (id === 'history') loadHistory()
}

function addLog(message, details = {}) {
  logs.value.unshift({ timestamp: new Date().toISOString(), stage: 'ui', source: 'frontend', message, ...details })
}

function logText(log) {
  return typeof log === 'string' ? log : log.message
}

function logTime(log, index) {
  if (typeof log === 'object' && log.timestamp) return log.timestamp.slice(11, 19)
  return `09:${String(20 - index).padStart(2, '0')}`
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
  currentStage.value = full.stages?.at(-1)?.stage || full.stages?.at(-1)?.name || '历史任务已恢复'
  if (Array.isArray(full.stages)) stages.value = full.stages
  if (Array.isArray(full.result?.fleet)) updateDrones(full.result)
  loadEvents(task.analysis_id)
  viewTab.value = 'overview'
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

async function downloadReport() {
  if (!analysisId.value) return
  const response = await fetch(`/api/tasks/${analysisId.value}/report/download`)
  if (!response.ok) { errorMessage.value = '报告暂不可用。'; return }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `task-${analysisId.value}-dispatch_plan.json`
  link.click()
  URL.revokeObjectURL(url)
}

async function toggleReport() {
  if (!analysisId.value) { errorMessage.value = '暂无任务报告，请先完成一次研判。'; return }
  reportViewer.value.open = !reportViewer.value.open
  if (!reportViewer.value.open) return
  reportViewer.value.loading = true
  try {
    const response = await fetch(`/api/tasks/${analysisId.value}/report`)
    if (!response.ok) throw new Error('报告接口不可用')
    reportViewer.value.data = await response.json()
  } catch (error) {
    errorMessage.value = '报告暂不可用。'
    reportViewer.value.open = false
    console.warn(error)
  } finally {
    reportViewer.value.loading = false
  }
}

const reportJson = computed(() => reportViewer.value.data ? JSON.stringify(reportViewer.value.data, null, 2) : '正在加载报告…')
// 报告格式化卡（FE-22，范式参考 firepatrol ReportCard）：结论 + 统计格 + 折叠时间线
const reportCard = computed(() => {
  const data = reportViewer.value.data
  if (!data) return null
  const result = data.result || {}
  const plan = result.dispatch_plan || {}
  const time = plan.estimated_control_time || {}
  const rounds = Array.isArray(data.rounds) ? data.rounds : []
  const events = Array.isArray(data.events) ? data.events : []
  const fireFlp = (result.fire_assessment || {}).fire_load_flp
  const initial = rounds.length && rounds[0].before ? rounds[0].before.fire_load_flp : fireFlp
  const latest = rounds.length && rounds.at(-1).after ? rounds.at(-1).after.fire_load_flp : fireFlp
  const timeWindow = time.earliest_minutes != null ? `${time.earliest_minutes}–${time.latest_minutes} 分钟` : '—'
  return {
    canControl: Boolean(plan.can_control),
    conclusion: plan.can_control ? '可控制 · 处置方案成立' : '暂不可控 · 已输出资源缺口',
    statusLabel: statusLabels[data.status] || data.status || '—',
    stats: [
      { label: '方案版本', value: (data.plan_versions || []).length },
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
  // 静默拦截，按钮永远不可用）；指挥中枢面板仍强制填写原因
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
const streamMode = ref('agent') // 大屏右栏：协作流（六角色黑板消息）/ 事件流（任务事件）
// —— 三维地形（FE-29）：高程网格懒加载 + 演示态势投影 ——
const mapMode = ref('2d')
const terrainGrid = ref(null)
const terrainGridLoading = ref(false)
async function loadTerrainGrid() {
  if (terrainGrid.value || terrainGridLoading.value) return
  terrainGridLoading.value = true
  try {
    const { latitude, longitude } = environmentCoordinates.value
    const query = new URLSearchParams({ latitude: String(latitude), longitude: String(longitude), radius_deg: '0.04', size: '141' })
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
  const preferred = environment.value && environment.value.preferred_water
  if (preferred && preferred.latitude != null) stations.push({ name: preferred.name || '首选水源', gps: { latitude: Number(preferred.latitude), longitude: Number(preferred.longitude) }, color: '#5fb8d9' })
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

function openFilePicker() {
  fileInput.value?.click()
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

function handleFileChange(event) {
  acceptFile(event.target.files)
  event.target.value = ''
}

function handleDrop(event) {
  acceptFile(event.dataTransfer.files)
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
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
    const stages = [['正在解析航拍影像…', 24, '正在解析影像'], ['规则演示视觉识别完成 · YOLO 待接入', 48, '视觉识别（演示）'], ['正在融合风场与地形数据…', 72, '环境融合'], ['正在生成集群调度方案…', 90, '调度生成']]
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

// ---------- 出动推演（FE-17）：批准即动画，自动轮次推进，后端权威校准 ----------
// 相位时间线与后端 simulate_monitor 状态机对齐（flying→working→returning→servicing→charging）
const MISSION_MS_PER_MIN = 1200 // 1 仿真分钟 ≈ 1.2 实秒（一轮 5 仿真分钟 ≈ 6s）
const MISSION_ROUND_MS = 6000
const MISSION_PHASE_LABELS = { flying: '出动中', working: '喷洒作业', returning: '返航中', servicing: '基地补水', charging: '基地充电', orbit: '侦察盘旋', parked: '待命' }
const mission = ref(null)
const missionNow = ref(0)
let missionTimer = null
let missionClockTimer = null

function fireGpsValue() {
  const gps = analysisResult.value?.scene?.fire_origin_gps
  if (gps && Number.isFinite(Number(gps.latitude)) && Number.isFinite(Number(gps.longitude))) {
    return { latitude: Number(gps.latitude), longitude: Number(gps.longitude) }
  }
  return environmentCoordinates.value
}

function buildMission() {
  const origin = analysisResult.value?.scene?.fire_origin
  if (!origin) return null
  const selected = new Set(plan.value.selected_uavs || [])
  // 注意：本模块作用域内 Map 被 lucide 图标组件遮蔽，不能用 new Map()
  const battery = {}
  for (const entry of plan.value.battery_plan || []) battery[entry.uav_id] = entry
  const units = []
  for (const drone of drones.value) {
    if (!drone.position) continue
    const dx = drone.position.x - origin.x
    const dy = drone.position.y - origin.y
    const outboundByDistance = Math.max(0.5, distanceMeters(dx, dy) / Math.max(drone.speed_mps, 0.1) / 60)
    let phases
    let kind = 'support'
    const entry = battery[drone.id]
    if (selected.has(drone.id) && drone.subgroup === 'suppression' && entry) {
      const outbound = Math.max(0.5, Number(entry.outbound_minutes) || outboundByDistance)
      const chargeMinutes = Math.max(3, Math.round(((100 - (entry.soc_after_return ?? drone.soc ?? 90)) / 100) * 60))
      phases = [
        { kind: 'flying', minutes: outbound },
        { kind: 'working', minutes: 5 },
        { kind: 'returning', minutes: outbound },
        { kind: 'servicing', minutes: 4 },
        { kind: 'charging', minutes: chargeMinutes },
      ]
      kind = 'suppression'
    } else if (selected.has(drone.id) && drone.subgroup === 'reconnaissance') {
      phases = [
        { kind: 'flying', minutes: outboundByDistance },
        { kind: 'orbit', minutes: Infinity },
      ]
      kind = 'recon'
    } else {
      phases = [{ kind: 'parked', minutes: Infinity }]
    }
    units.push({ id: drone.id, dx, dy, kind, soc: Number(drone.soc ?? 90), phases, anchor: 0 })
  }
  if (!units.length) return null
  return { active: true, startedAt: Date.now(), units }
}

function distanceMeters(dx, dy) {
  return Math.hypot(dx, dy)
}

function missionPhaseAt(phases, tMinutes) {
  let acc = 0
  for (const phase of phases) {
    if (phase.minutes === Infinity) return { kind: phase.kind, progress: 0 }
    if (tMinutes < acc + phase.minutes) return { kind: phase.kind, progress: Math.max(0, (tMinutes - acc) / phase.minutes) }
    acc += phase.minutes
  }
  const last = phases[phases.length - 1]
  return { kind: last.kind, progress: 1 }
}

function missionPhaseText(id) {
  if (!mission.value?.active) return ''
  const unit = mission.value.units.find((item) => item.id === id)
  if (!unit) return ''
  return MISSION_PHASE_LABELS[missionPhaseAt(unit.phases, missionNow.value).kind] || ''
}

function startMission() {
  mission.value = buildMission()
  if (!mission.value) return
  missionNow.value = 0
  addLog('出动动画开始 · 机群自紫霞湖基地向火点转进', { stage: 'mission', source: 'local' })
  missionClockTimer = window.setInterval(() => {
    if (mission.value?.active) missionNow.value = (Date.now() - mission.value.startedAt) / MISSION_MS_PER_MIN
  }, 500)
  startAutoSim()
}

function stopMission(park = true) {
  stopAutoSim()
  if (missionClockTimer) { window.clearInterval(missionClockTimer); missionClockTimer = null }
  if (mission.value && park) mission.value = { ...mission.value, active: false }
}

function startAutoSim() {
  stopAutoSim()
  missionTimer = window.setInterval(() => { runMonitor(true) }, MISSION_ROUND_MS)
}

function stopAutoSim() {
  if (missionTimer) { window.clearInterval(missionTimer); missionTimer = null }
}

function reconcileMission(after) {
  if (!mission.value?.active || !after) return
  const battery = {}
  for (const entry of after.battery_plan || []) battery[entry.uav_id] = entry
  for (const unit of mission.value.units) {
    const entry = battery[unit.id]
    if (!entry) continue
    if (Number.isFinite(Number(entry.soc_after))) unit.soc = Number(entry.soc_after)
    const statusToKind = { flying: 'flying', working: 'working', returning: 'returning', servicing: 'servicing', charging: 'charging', available: 'charging' }
    const target = statusToKind[entry.status]
    if (!target) continue
    // 相位软校准：把该单元时钟锚点平移到后端判定的相位起点，保持地图与仿真一致
    let acc = 0
    for (const phase of unit.phases) {
      if (phase.kind === target) { unit.anchor = acc - (Date.now() - mission.value.startedAt) / MISSION_MS_PER_MIN; break }
      if (phase.minutes === Infinity) break
      acc += phase.minutes
    }
  }
}

// ---------- 出动推演结束 ----------

// ---------- 演训模拟（FE-18）：随机火情生成 + 开始模拟 ----------
const ZIXIAHU_BASE_GPS = { latitude: 32.062229, longitude: 118.839016 } // 紫霞湖水库：机群基地真实锚点
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
  resetAnalysis()
  const base = fleetAveragePosition()
  const distance = 800 + Math.random() * 1700
  const angle = ((-25 + Math.random() * 100) * Math.PI) / 180
  const fireOrigin = { x: Math.round(base.x + Math.cos(angle) * distance), y: Math.round(base.y + Math.sin(angle) * distance) }
  // FE-43：面积分层抽样——编队持续压制 ≈13 FLP/轮，300-6000 均匀分布下大多数随机火
  // 超出能力（可胜区 ≤~900m²），「生成→扑灭」演示主流程应当多数落在可胜区间；
  // 大火保留 10% 概率供失控/增援演练，重摇即可遇到
  const sizeRoll = Math.random()
  const areaM2 = Math.round(sizeRoll < 0.6 ? 300 + Math.random() * 600 : sizeRoll < 0.9 ? 900 + Math.random() * 1600 : 2500 + Math.random() * 3500)
  const growthRate = Math.round((0.2 + Math.random() * 0.4) * 100) / 100
  const people = ['confirmed', 'absent', 'unknown'][Math.floor(Math.random() * 3)]
  const metersPerLng = 111320 * Math.cos((ZIXIAHU_BASE_GPS.latitude * Math.PI) / 180)
  const fireGps = {
    latitude: +(ZIXIAHU_BASE_GPS.latitude + (fireOrigin.y - base.y) / 111320).toFixed(6),
    longitude: +(ZIXIAHU_BASE_GPS.longitude + (fireOrigin.x - base.x) / metersPerLng).toFixed(6),
  }
  peopleStatus.value = people
  // 演练互斥（FE-34/35）：风变重规划可能生成无灭火机方案，与失能演练语义冲突，二选一
  const drillRoll = Math.random()
  const failureRound = drillRoll < 0.35 ? 2 + Math.floor(Math.random() * 3) : null
  // FE-44：风变目标必须真跨档（档位 0-4/4-6/6-8/8+）——旧逻辑 base+2.5 在低风天
  // 仍同档（1.35→3.9 同在 band 0），风变重规划静默失效；按基准档位取下一档中值
  const baseWind = Number(result.value.environment.wind_speed) || 0
  const windShift = failureRound ? null : (Math.random() < 0.4 ? { round: 2 + Math.floor(Math.random() * 3), speed: baseWind < 4 ? 5.5 : baseWind < 6 ? 7.5 : baseWind < 8 ? 8.6 : 5.2 } : null)
  scenario.value = { fireOrigin, fireGps, areaM2, growthRate, people, failureRound, windShift }
  const peopleLabel = people === 'confirmed' ? '在场' : people === 'absent' ? '不在场' : '情况不明'
  addLog(`随机火情已生成 · 面积 ${areaM2}m² · 人员${peopleLabel} · 演训模拟就绪`, { stage: 'scenario', source: 'local' })
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
  if (event.key !== 'Escape') return
  if (activeMarker.value) { activeMarker.value = null; return }
  if (reportViewer.value.open) toggleReport()
}

onMounted(() => { window.addEventListener('keydown', onKeydown); refreshLlmInfo(); llmPollTimer = window.setInterval(refreshLlmInfo, 30000) })
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  if (llmPollTimer) { window.clearInterval(llmPollTimer); llmPollTimer = null }
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
})
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><div class="brand-mark"><Flame :size="19" /></div><div><strong>EMBER<span>OS</span></strong><small>RESCUE INTELLIGENCE</small></div></div>
      <div class="scene-card"><div class="eyebrow">CURRENT SCENE</div><div class="scene-name">{{ scene.name }} · 01</div><div class="scene-meta"><span class="live-dot"></span> LIVE SIMULATION <span class="scene-time">09:20:14</span></div></div>
      <nav aria-label="主导航"><button v-for="item in navItems" :key="item.id" :class="{ active: activeTab === item.id }" @click="selectNav(item.id)"><component :is="item.icon" :size="17" /><span>{{ item.label }}</span><b v-if="item.id === 'fleet'">{{ drones.length }}</b></button></nav>
      <div class="sidebar-foot"><div class="system-status"><span :class="['live-dot', { offline: !serviceOnline }]" /><div><strong>{{ serviceOnline ? '系统运行正常' : '本地演示模式' }}</strong><small>{{ serviceOnline ? '后端服务在线' : '后端服务未连接' }}</small></div></div><div class="operator"><div class="avatar">江</div><div><strong>江月</strong><small>指挥员 · OP-07</small></div><ChevronRight :size="16" /></div></div>
    </aside>

    <main :class="{ 'main-map': activeTab === 'map' }">
      <header><div><div class="breadcrumb">COMMAND CENTER <span>/</span> {{ activeTab.toUpperCase() }}</div><h1>森林火灾救援工作台</h1><p>多源感知 · 智能研判 · 集群调度 · 闭环处置</p></div><div class="header-actions"><button class="icon-btn" title="查看任务事件通知" @click="selectNav('logs')"><Bell :size="18" /><i></i></button><span class="status-tag" :class="llmInfo?.available ? '' : 'orange'" :title="llmInfo?.available ? 'GLM 在线研判' : 'LLM 未配置 · 确定性降级'"><Activity :size="14" /> LLM {{ llmInfo?.available ? '在线' : '离线' }}</span><div class="utc">本地时间<br><strong>{{ todayLabel }}</strong></div></div></header>
      <section class="toolbar"><div class="tab-pills" role="tablist" aria-label="任务视图"><button role="tab" :aria-selected="viewTab === 'overview'" :class="{ selected: viewTab === 'overview' }" @click="selectView('overview')">任务概览</button><button role="tab" :aria-selected="viewTab === 'monitor'" :class="{ selected: viewTab === 'monitor' }" @click="selectView('monitor')">实时监测</button><button role="tab" :aria-selected="viewTab === 'history'" :class="{ selected: viewTab === 'history' }" @click="selectView('history')">历史任务</button><button role="tab" :aria-selected="viewTab === 'agents'" :class="{ selected: viewTab === 'agents' }" @click="selectView('agents')">Agent 协作</button></div><div class="toolbar-right"><span class="task-badge">任务状态 · {{ displayStatus }}</span><span class="sync"><span class="live-dot"></span> {{ currentStage }}</span><button class="primary" :disabled="analyzing" @click="startAnalysis"><Bot :size="17" /> {{ analyzing ? '分析中…' : '启动智能研判' }}</button></div></section>
      <div v-if="errorMessage" class="notice" role="status"><Activity :size="16" /><span>{{ errorMessage }}</span><button v-if="canRetryAnalysis" class="outline-btn notice-retry" :disabled="analyzing" @click="startAnalysis">重试研判</button><button class="notice-close" title="关闭提示" @click="errorMessage = ''">×</button></div>

      <div v-if="activeTab === 'command'" class="dashboard">
        <section class="hero-panel"><div class="panel-heading"><h2>{{ scene.incident }}</h2><span class="severity"><span></span>{{ result.fire_assessment.label }}</span></div><p class="hero-note">火点 <b>{{ scene.coordinates }}</b> · 现场风 <b>{{ result.environment.wind_direction || '—' }} {{ result.environment.wind_speed ?? '—' }} m/s</b> · 最近水源 <b>{{ result.environment.nearest_water?.name || '—' }} {{ result.environment.nearest_water?.distance_m ?? result.environment.nearest_water_distance_m ?? '' }}</b></p><div class="hero-footer" :class="result.dispatch_plan.can_control ? 'ok' : 'bad'"><div><small>当前处置结论</small><strong>{{ result.dispatch_plan.can_control ? '可控制 · 建议立即出动' : '暂不可控 · 请求增援' }}</strong></div><div class="hero-stat"><small>预计处置时间</small><strong>{{ result.dispatch_plan.estimated_minutes ?? '—' }} <em>MIN</em></strong></div><div class="hero-stat"><small>下次评估</small><strong>05 <em>MIN</em></strong></div></div></section>

        <section class="upload-panel"><div class="panel-heading"><h2>现场影像接入</h2><FileImage :size="19" class="muted-icon" /></div><input ref="fileInput" class="visually-hidden" type="file" accept="image/jpeg,image/png,video/mp4" multiple @change="handleFileChange"><div class="dropzone" :class="{ uploaded }" @click="openFilePicker" @dragover.prevent @drop.prevent="handleDrop"><div v-if="previewUrl && selectedFile?.type.startsWith('image/')" class="preview-thumb"><img :src="previewUrl" alt="已选择的火灾影像预览"></div><div v-else class="upload-orb"><Upload :size="22" /></div><strong>{{ uploaded ? (selectedFrames.length ? `影像已接入 · 序列 ${selectedFrames.length + 1} 帧` : '影像已接入') : '拖入航拍图像或视频' }}</strong><span>{{ uploaded ? `${selectedFile.name}${selectedFrames.length ? ` + ${selectedFrames.length} 帧序列` : ''} · ${(selectedFile.size / 1024 / 1024).toFixed(1)} MB` : '支持 JPG / PNG / MP4 · 多选图片组成序列 · 最大 200MB' }}</span><button type="button" @click.stop="openFilePicker">{{ uploaded ? '更换文件' : '选择文件' }}</button></div><div class="process"><div class="process-row"><span>分析管线</span><b>{{ progress }}%</b></div><div class="progress"><i :style="{ width: progress + '%' }"></i></div><div class="pipeline"><span :class="{ done: progress >= 24 }">视觉识别</span><ChevronRight :size="13" /><span :class="{ done: progress >= 48 }">环境融合</span><ChevronRight :size="13" /><span :class="{ done: progress >= 72 }">风险评估</span><ChevronRight :size="13" /><span :class="{ done: progress >= 90 }">调度生成</span></div><div class="model-status"><span>YOLO <b>{{ projectStatus.yolo === 'pending' ? '待接入' : projectStatus.yolo === 'configured' ? '已配置' : '在线' }}</b></span><span>VLM <b>{{ projectStatus.vlm === 'pending' ? '待接入' : projectStatus.vlm === 'configured' ? '已配置' : '在线' }}</b></span><span>场景数据 <b>{{ projectStatus.geo_data }}</b></span><label class="vlm-toggle"><input type="checkbox" v-model="useVlm"> 上传时调用 VLM 解释</label></div></div><button v-if="uploaded" class="reset-link" @click="resetAnalysis"><RefreshCw :size="13" /> 清空并重新接入</button><div class="scenario-block"><div class="scenario-head"><b>演训模拟</b><small>无需影像 · 随机生成紫金山火情</small></div><div v-if="!scenario" class="scenario-empty">点击生成一处在紫金山范围内随机出现的火情，随后开始模拟集群调度推演。</div><div v-else class="scenario-facts"><span>火点 <b>{{ scenario.fireGps.longitude }}°E, {{ scenario.fireGps.latitude }}°N</b></span><span>面积 <b>{{ scenario.areaM2 }} m²</b></span><span>增长率 <b>{{ scenario.growthRate }}/h</b></span><span>人员 <b>{{ scenario.people === 'confirmed' ? '在场' : scenario.people === 'absent' ? '不在场' : '情况不明' }}</b></span><span v-if="scenario.failureRound" class="scenario-drill">⚔ 含单机失能演练（第 {{ scenario.failureRound }} 轮）</span><span v-if="scenario.windShift" class="scenario-drill">🌪 风变演练（第 {{ scenario.windShift.round }} 轮 · {{ scenario.windShift.speed }} m/s）</span></div><div class="scenario-actions"><button class="outline-btn" :disabled="scenarioBusy || analyzing" @click="generateScenario">{{ scenario ? '重新生成火情' : '生成随机火情' }}</button><button v-if="scenario" class="primary scenario-start" :disabled="scenarioBusy || analyzing" @click="startScenarioSimulation"><Bot :size="16" /> 开始模拟</button></div></div></section>

        <section class="environment-panel panel"><div class="panel-heading"><h2>现场环境</h2><button class="outline-btn environment-refresh" :disabled="environmentLoading" @click="loadEnvironment"><RefreshCw :size="14" /> {{ environmentLoading ? '刷新中…' : '刷新环境' }}</button></div><div class="environment-controls"><label>模式 <select v-model="environmentMode" @change="loadEnvironment"><option value="real">真实数据</option><option value="auto">自动</option><option value="offline">离线演示（不联网）</option><option value="demo">演示数据</option></select></label><div class="coordinate-editor"><label>纬度 <input v-model="coordinateDraft.latitude" inputmode="decimal" aria-label="纬度"></label><label>经度 <input v-model="coordinateDraft.longitude" inputmode="decimal" aria-label="经度"></label><button class="outline-btn" type="button" @click="applyCoordinates">应用</button></div><span>{{ environmentCoordinates.latitude.toFixed(6) }}, {{ environmentCoordinates.longitude.toFixed(6) }}</span></div><div v-if="coordinateError" class="coordinate-error" role="alert">{{ coordinateError }}</div><div class="environment-meta"><span>采集 · {{ environment?.collected_at?.slice(0, 19).replace('T', ' ') || '—' }}</span><span>状态 · {{ environmentStatus }}</span><span>来源 · {{ environmentSource }}</span><span v-if="environmentStale">stale / 缓存</span><span v-if="environmentFallback">fallback · {{ environmentFallback }}</span></div><div class="environment-grid"><div v-for="item in environmentFeatures" :key="item.label" class="environment-item"><span>{{ item.label }}</span><strong :class="['tone-' + item.tone, { 'is-empty': item.empty }]">{{ item.value }}</strong></div></div></section>
        <section class="metrics-grid"><article v-for="metric in metrics" :key="metric.label" class="metric-card"><div class="metric-top"><span>{{ metric.label }}</span><component :is="metric.icon" :size="17" :class="'tone-' + metric.tone" /></div><div class="metric-value">{{ metric.value }} <small>{{ metric.unit }}</small></div><div :class="['metric-change', 'tone-' + metric.tone]">{{ metric.change }}</div></article></section>
        <section class="fleet-panel panel"><div class="panel-heading"><h2>无人机集群状态</h2><button class="text-btn" @click="selectNav('fleet')">查看详情 <ChevronRight :size="14" /></button></div><div class="fleet-list"><template v-if="!drones.length"><div class="skeleton-row"></div><div class="skeleton-row"></div><div class="skeleton-row"></div></template><div v-for="drone in drones" :key="drone.id" class="drone-row"><div :class="['drone-icon', drone.color]"><Zap :size="17" /></div><div class="drone-name"><strong>{{ drone.id }} <span>{{ drone.label }}</span></strong><small>{{ drone.subgroup }} · {{ drone.status }}</small></div><div class="battery"><div class="battery-bar"><i :style="{ width: drone.soc + '%' }"></i></div><span>SOC {{ drone.soc }}%</span></div><div class="drone-telemetry"><span>模块 {{ moduleLabel(drone.module) }}</span><span>药剂 {{ drone.payload }}</span><span>信号 {{ drone.signal }}%</span><span>健康 {{ drone.health }}%</span></div><span :class="['drone-status', drone.status === '执行中' ? 'active-status' : '']"><i></i>{{ drone.status }}</span></div></div></section>
        <section class="decision-panel panel"><div class="panel-heading"><h2>调度建议</h2><span class="ai-badge"><Bot :size="14" /> {{ dataMode }}</span></div><div class="decision-callout"><div class="decision-icon"><Gauge :size="20" /></div><div><strong>{{ result.dispatch_plan.can_control ? '建议立即启动一级处置响应' : '建议立即请求增援' }}</strong><p>{{ result.explanation }}</p></div></div><div v-if="vlmNote" class="vlm-note"><div class="vlm-note-head"><b>VLM 视觉解释</b><span class="src-note">{{ vlmNoteSource }}</span></div><p v-if="vlmNoteBody">{{ vlmNoteBody }}</p><p v-else class="muted">模型未返回摘要文本</p><div v-if="vlmNoteFacts.length" class="vlm-note-facts"><span v-for="(fact, i) in vlmNoteFacts" :key="i" :class="{ 'vlm-flag': fact === '需人工复核' }">{{ fact }}</span></div><ul v-if="vlmNoteIssues.length" class="vlm-note-issues"><li v-for="(issue, i) in vlmNoteIssues" :key="i">{{ issue }}</li></ul></div><div v-if="frameTrendText" class="src-note frame-trend">{{ frameTrendText }}</div><div v-if="inputProvenanceText" class="src-note">{{ inputProvenanceText }}</div><div class="plan-summary" v-if="analysisEnvelope && (analysisEnvelope?.status === 'awaiting_confirmation' || analysisEnvelope?.plan_versions?.length)"><b>方案 {{ planVersionLabel }}</b><span>FLP：{{ plan.fire_load_flp ?? result.dispatch_plan.fire_load_flp ?? '—' }}</span><span>主方案：{{ currentPlanId || '当前方案' }}</span><span>时间区间：{{ controlWindow }}</span><span>硬约束：{{ plan.hard_constraints?.length ? plan.hard_constraints.join('、') : (plan.resource_gap?.some((gap) => gap.resource === 'hard_constraint') ? '存在冲突' : '满足') }}</span><span>备选：{{ plan.alternative_plan?.length ? `${plan.alternative_plan.length} 个` : '暂无' }}</span><span>缺口：{{ resourceGap.length ? resourceGap.map((gap) => gap.name || gap.resource || gap.type).join('、') : '无' }}</span><span>重规划：{{ plan.replan_trigger?.length ? plan.replan_trigger.join('、') : '未触发' }}</span><span v-if="evacuationSummary" class="evacuation-summary">疏散：{{ evacuationSummary }}</span><span v-if="result.fire_params_source === 'vlm-visual-assessment'" class="src-note vlm-mapped">火情规模 ← VLM 视觉评估({{ result.fire_params_scale }})· 火随图变</span><span class="src-note">数字来源 · FLP ← 火情负荷评估 · 时间区间 ← 离散轮次仿真 · 约束/缺口 ← 规则引擎硬约束校验</span></div><div class="people-risk"><label>人员状态 <select v-model="peopleStatus"><option value="confirmed">有人</option><option value="absent">无人</option><option value="unknown">不确定</option></select></label><label>出动上限 <select v-model.number="maxDrones" title="调整方案时生效的灭火机数量上限（可灭火机：E1-E6 + 多用途 S3/S4）"><option v-for="n in maxDronesOptions" :key="n" :value="n">{{ n }}</option></select></label><label>时限 <input class="minute-input" type="number" min="1" v-model.number="targetMinutes" placeholder="min" title="调整方案时生效的目标处置时限（分钟）"></label><label class="uav-disable">禁用 <template v-for="uid in disableOptions" :key="uid"><input type="checkbox" :value="uid" v-model="disabledUavs"><span>{{ uid }}</span> </template></label><span>{{ peopleRisk }}</span></div><div class="approval-actions" v-if="analysisId"><input class="reason-input" v-model="reasonInput" placeholder="驳回/终止原因（必填）" aria-label="操作原因"><button class="outline-btn" :disabled="approvalBusy" @click="submitApproval('approve')">批准主方案</button><button class="outline-btn" :disabled="approvalBusy" @click="submitApproval('adjust')">按约束调整</button><button class="outline-btn danger-btn" :disabled="approvalBusy" @click="submitApproval('reject')">驳回</button><button class="outline-btn danger-btn" :disabled="approvalBusy" @click="submitApproval('terminate')">终止任务</button><button class="outline-btn" @click="toggleReport">{{ reportViewer.open ? '收起报告' : '在线查看报告' }}</button><button class="outline-btn" @click="downloadReport">下载报告 JSON</button></div><div v-if="reportViewer.open" class="report-viewer"><div class="report-viewer-head"><b>任务报告 · {{ analysisId }}</b><small>data/reports/{{ analysisId }}/dispatch_plan.json</small></div><template v-if="reportCard"><div :class="['report-conclusion', reportCard.canControl ? 'ok' : 'bad']"><b>{{ reportCard.conclusion }}</b><span>{{ reportCard.statusLabel }} · 数字均出自规则引擎</span></div><div class="report-stats"><div v-for="s in reportCard.stats" :key="s.label" class="report-stat"><b>{{ s.value }}</b><span>{{ s.label }}</span></div></div><details><summary>全链路时间线（{{ reportCard.events.length }} 条）</summary><ul class="report-events"><li v-for="(e, i) in reportCard.events" :key="i"><span class="log-time">{{ e.time }}</span><b>{{ e.stage }}</b>{{ e.message }}</li></ul></details><details class="report-raw"><summary>原始 JSON</summary><pre>{{ reportJson }}</pre></details></template><pre v-else>{{ reportJson }}</pre></div><div class="task-chips"><span v-for="task in result.dispatch_plan.tasks" :key="task.drone_id"><b>{{ task.drone_id }}</b> {{ task.task }}</span></div><button v-if="analysisResult" class="monitor-btn" :disabled="monitoring" @click="runMonitor()"><RefreshCw :size="14" /> {{ monitoring ? '推演中…' : '执行下一轮监测' }}</button><span v-if="mission?.active" class="sim-clock">自动推演 · 第 {{ Math.min(Math.floor(missionNow / 5) + 1, activeRounds.length + 1) }} 轮 · {{ Math.floor(missionNow % 5) }}/5 min</span><div v-if="monitorResult" class="monitor-result">第 {{ analysisEnvelope?.monitor_round || activeRounds.length }} 轮 · 监测结果：火焰面积 {{ monitorArea }}m² · FLP {{ monitorResult.fire_load_flp ?? monitorResult.next_fire_load_flp ?? '—' }} · SOC {{ monitorResult.next_fleet?.map((drone) => `${drone.id}:${drone.soc ?? drone.battery}%`).join('、') || '—' }} · 库存 {{ monitorResult.next_inventory ? `水 ${monitorResult.next_inventory.water_liters ?? 0}L / W20×${monitorResult.next_inventory.water_modules_w20 ?? 0} / C6×${monitorResult.next_inventory.co2_modules_c6 ?? 0} / 电池×${monitorResult.next_inventory.battery_packs ?? 0}` : '—' }} · {{ monitorResult.reason || '无重规划原因' }}</div><div v-if="activeRounds.length" class="round-list"><div v-for="round in activeRounds" :key="round.round || round.monitor_round"><b>Round {{ round.round || round.monitor_round }}</b><span>before FLP {{ round.before?.fire_load_flp ?? round.before?.fire_load ?? '—' }}</span><span>after FLP {{ round.after?.fire_load_flp ?? round.after?.fire_load ?? '—' }}</span><span>触发原因：{{ (round.replan_triggers || round.replan_trigger || []).join('、') || '无' }}</span><span v-if="round.next_action">动作 {{ round.next_action === 'awaiting_confirmation' ? '等待二次审批' : round.next_action === 'finish' ? '火情扑灭·结案' : round.next_action }}</span></div></div></section>
        <section class="chat-panel panel"><ChatPanel :task-id="analysisId" :enabled="chatEnabled" /></section>
        <section class="log-panel panel"><div class="panel-heading"><h2>任务日志</h2><span class="log-count">{{ logs.length }} EVENTS</span></div><div class="logs"><div v-if="!logs.length" class="empty-hint"><b>暂无事件</b>启动研判或执行操作后，任务事件会实时显示在这里。</div><div v-for="(log, index) in logs.slice(0, 6)" :key="log.message + log.timestamp + index"><span class="log-time">{{ logTime(log, index) }}</span><i :class="{ bright: index === 0 }"></i><span>{{ logText(log) }} <small v-if="typeof log === 'object'">· {{ log.stage }} / {{ log.source }}</small></span></div></div></section>
      </div>

      <section v-else-if="activeTab === 'fleet'" class="detail-view"><div class="detail-heading"><div><h2>无人机集群</h2><p>当前集群共有 {{ drones.length }} 架无人机，状态数据来自 /api/fleet。</p></div><span class="status-tag"><span class="live-dot"></span> 全部在线</span></div><div class="fleet-roster"><div v-for="group in fleetGroups" :key="group.key" class="roster-group"><div class="roster-group-head"><b>{{ group.label }}</b><small>{{ group.drones.length }} 架 · {{ group.role }}</small></div><div class="roster-table"><div v-for="drone in group.drones" :key="drone.id" class="roster-row"><div class="roster-id"><div :class="['drone-icon', drone.color]"><Zap :size="16" /></div><div><strong>{{ drone.id }}</strong><span>{{ drone.label }}</span></div></div><span :class="['roster-state', drone.status === '执行中' ? 'active-status' : '']"><i></i>{{ drone.status }}</span><div class="roster-soc"><div class="battery-bar"><i :style="{ width: drone.soc + '%' }"></i></div><b>{{ drone.soc }}%</b></div><span class="roster-payload">模块 {{ moduleLabel(drone.module) }} · 药剂 {{ drone.payload }}</span><span class="roster-num"><small>信号</small>{{ drone.signal }}%</span><span class="roster-num"><small>健康</small>{{ drone.health }}%</span><span class="roster-task" :title="drone.task">{{ drone.task }}</span><button class="outline-btn" @click="toggleFleetDetail(drone.id)"><ListFilter :size="14" /> {{ expandedFleet.has(drone.id) ? '收起遥测' : '遥测' }}</button><div v-if="expandedFleet.has(drone.id)" class="fleet-detail-extra"><span>速度 {{ drone.speed_mps ?? '—' }} m/s</span><span>耗电 {{ drone.energy_rate_percent_per_hour ?? '—' }} %/h</span><span>高度 {{ (drone.position && drone.position.z != null) ? drone.position.z + ' m' : '—' }}</span><span>编号 {{ drone.uav_id || drone.id }}</span><span>任务 {{ drone.task }}</span></div></div></div></div></div></section>

      <section v-else-if="activeTab === 'map'" class="detail-view map-view map-view-full screen"><div class="map-toolbar"><div class="map-toolbar-heading"><h2>林区态势</h2><PhaseStepper :stage="screenStage.stage" :done="screenStage.done" :dead="screenStage.dead" :replans="replanCount" /></div><div class="map-toolbar-tools"><span class="view-toggle"><button :class="['legend-item', { on: mapMode === '2d' }]" :aria-pressed="mapMode === '2d'" @click.stop="toggleMapMode('2d')">🗺 平面</button><button :class="['legend-item', { on: mapMode === '3d' }]" :aria-pressed="mapMode === '3d'" @click.stop="toggleMapMode('3d')">🏔 三维</button></span><div class="map-legend" role="group" aria-label="图层开关"><button v-for="(label, key) in LAYER_LABELS" :key="key" :class="['legend-item', { off: !layerVisibility[key] }]" :aria-pressed="layerVisibility[key]" @click.stop="toggleLayer(key)"><i :class="'legend-' + key"></i>{{ label }}</button></div><button :class="['legend-item', { off: !voiceOn }]" :aria-pressed="voiceOn" :title="voiceOn ? '疏散语音广播已开启（点击静音）' : '疏散语音广播已静音（点击开启）'" @click.stop="toggleVoice"><i class="legend-evac"></i>语音广播</button><span class="status-tag orange"><MapPinned :size="14" /> {{ environmentCoordinates.longitude.toFixed(6) }}°E · {{ environmentCoordinates.latitude.toFixed(6) }}°N</span></div></div>
      <div class="screen-kpis"><div v-for="kpi in screenKpis" :key="kpi.label" :class="['skpi', 'tone-' + kpi.tone]"><b>{{ kpi.value }}<small>{{ kpi.unit }}</small></b><span>{{ kpi.label }}<em>{{ kpi.sub }}</em></span></div></div>
      <div class="map-taskbar" role="toolbar" aria-label="任务控制">
        <template v-if="!analysisResult && !scenario">
          <button class="scr-btn" :disabled="analyzing" @click="generateScenario"><span>🎲</span> 生成随机火情</button>
          <span class="scr-hint">一键生成紫金山随机火情并开始多智能体推演，或到「指挥中枢」上传影像研判</span>
        </template>
        <template v-else-if="scenario && !analysisResult">
          <span class="scr-hint">火情已生成 · 面积 {{ scenario.areaM2 }}m² · 增长率 {{ scenario.growthRate }}/h · 人员{{ scenario.people === 'confirmed' ? '在场' : scenario.people === 'absent' ? '不在场' : '情况不明' }}{{ scenario.failureRound ? ` · ⚔ 单机失能演练（第 ${scenario.failureRound} 轮）` : '' }}{{ scenario.windShift ? ` · 🌪 风变演练（第 ${scenario.windShift.round} 轮）` : '' }}</span>
          <button class="scr-btn" @click="generateScenario">🎲 重摇火情</button>
          <button class="scr-btn scr-primary" :disabled="scenarioBusy || analyzing" @click="startScenarioSimulation">{{ scenarioBusy ? '研判中…' : '▶ 开始模拟' }}</button>
        </template>
        <template v-else-if="analysisEnvelope && analysisEnvelope.status === 'awaiting_confirmation'">
          <span class="scr-hint">方案 {{ planVersionLabel }} 已生成 · {{ (result.dispatch_plan.selected_uavs || []).length }} 架出动 · {{ result.dispatch_plan.can_control ? '可控' : '超出能力，建议增援' }}</span>
          <button class="scr-btn scr-primary" :disabled="approvalBusy" @click="submitApproval('approve')">✅ 批准主方案</button>
          <button class="scr-btn" :disabled="approvalBusy" @click="submitApproval('terminate', { defaultReason: '指挥员在林区态势页终止任务' })">终止任务</button>
        </template>
        <template v-else-if="mission && mission.active">
          <span class="scr-hint scr-live"><i class="live-dot"></i> 自动推演中 · 第 {{ Math.min(Math.floor(missionNow / 5) + 1, activeRounds.length + 1) }} 轮 · 每轮 5 仿真分钟 · 结果见下方演化曲线与协作流</span>
        </template>
        <template v-else-if="taskStatus === '执行中'">
          <!-- FE-47：恢复的执行中任务落在推演钟不活跃分支，任务条不得误报「已结束」 -->
          <span class="scr-hint scr-live"><i class="live-dot"></i> 任务推演中（已完成 {{ analysisEnvelope?.monitor_round || 0 }} 轮）· 自动推演未启动，可在指挥中枢执行下一轮监测或批准新方案</span>
          <button class="scr-btn" :disabled="approvalBusy" @click="submitApproval('terminate', { defaultReason: '指挥员在林区态势页终止任务' })">终止任务</button>
        </template>
        <template v-else>
          <span class="scr-hint">任务已结束（{{ displayStatus }}）· 可重新开始一局</span>
          <button class="scr-btn" @click="generateScenario">🎲 生成随机火情</button>
        </template>
      </div>
      <div class="map-screen-body"><div class="map-main-col"><div class="tactical-map-wrap" @click="dismissMarker">
        <Terrain3D v-if="mapMode === '3d'" :grid="terrainGrid" :fire-gps="fire3dGps" :fire-radius-m="fire3dRadius" :fire-active="fire3dActive" :drones="drones" :mission="mission" :fire-origin="(analysisResult && analysisResult.scene ? analysisResult.scene.fire_origin : null)" :stations="stations3d" :evac-path="evac3dPath" :people-status="peopleStatus" />
        <TacticalMap v-else-if="amapReady && mapMode === '2d'" ref="tacticalMapRef" :result="result" :environment="environment" :drones="drones" :water-list="waterSourcesList" :contours="contourData" :layer-visibility="layerVisibility" :selected-uavs="(analysisResult?.dispatch_plan?.selected_uavs || [])" :mission="mission" :scenario-preview="scenarioPreview" :focus-pulse="focusPulse" :hovered-drone-id="hoveredDroneId" :hovered-water-id="hoveredWaterId" :active-marker-id="activeMarker?.id || ''" :default-center="environmentCoordinates" @select-marker="selectMarker" @coords="cursorCoords = $event" @ready="addLog('高德卫星底图加载完成')" @fallback="onAmapFallback" />
        <div v-else-if="mapMode === '2d'" class="large-map" @wheel.prevent="handleMapWheel" @pointerdown="startMapDrag" @pointermove="moveMap" @pointerup="stopMapDrag" @pointercancel="stopMapDrag" @pointerleave="stopMapDrag">
        <div class="map-scene-layer" :class="{ dragging: mapDragging }" :style="mapLayerStyle"><div class="terrain-wash"></div><div class="map-grid"></div><svg class="terrain-svg" viewBox="0 0 1000 520" preserveAspectRatio="none" aria-label="紫金山局部相对俯视等高线示意图"><defs><pattern id="topoGrid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M 40 0 L 0 0 0 40" fill="none" stroke="#b7a9a0" stroke-width=".6" opacity=".42"/></pattern></defs><rect width="1000" height="520" fill="url(#topoGrid)"/><g v-if="layerVisibility.contour" class="contours"><g v-for="line in contourPaths" :key="line.d"><path class="contour-line" :class="{ 'major-contour': line.major }" :d="line.d"/><text v-if="line.major && line.elevation != null" class="contour-label" :x="line.labelX" :y="line.labelY">{{ line.elevation }} m</text></g></g><circle class="summit-ring" cx="560" cy="248" r="16"/><text class="summit-label" x="560" y="244" text-anchor="middle">峰顶</text><text class="summit-elevation" x="560" y="258" text-anchor="middle">{{ terrainVisual.elevation }} m</text></svg><div class="terrain-caption"><strong>紫金山 · 局部地形态势</strong><span>SRTM DEM 实测等高线 · 标注实际位置</span></div><div class="contour-note"><span>等高距</span><b>{{ contourData?.interval_m ?? terrainVisual.contourStep }} m</b><small>{{ contourData?.source || '合成等高线' }}</small></div><div class="water-panel" aria-label="水源标注清单"><div class="water-panel-head"><b>水源标注</b><small>{{ waterSourcesList.length }} 处 · 按距离排序</small></div><div v-for="(water, index) in waterSourcesList.slice(0, 5)" :key="water.id" :class="['water-row', { preferred: water.preferred, linked: hoveredWaterId === water.id }]" @mouseenter="hoveredWaterId = water.id" @mouseleave="hoveredWaterId = ''" @click="water.position && selectMarker({ id: water.id, type: 'water', x: water.position.x, y: water.position.y })" :title="'点击查看水源详情'"><i class="water-dot" :class="'wt-' + waterTypeClass(water.type)"></i><b>{{ water.preferred ? '★ ' : '' }}{{ water.name }}</b><span>{{ water.type }} · {{ water.distance != null ? water.distance + 'm' : '距离未知' }}</span><small v-if="water.coordinates">{{ water.coordinates.longitude.toFixed(6) }}°E, {{ water.coordinates.latitude.toFixed(6) }}°N</small><small v-else>相对坐标</small></div><div v-if="!waterSourcesList.length" class="water-row"><span>当前环境无水源数据（可切换环境模式后刷新）</span></div></div><div v-for="(route, index) in mapRoutes" :key="route.name + index" class="route-line" :style="{ left: `${25 + index * 4}%`, top: `${48 + index * 3}%`, width: `${30 + (index % 3) * 8}%`, transform: `rotate(${-16 + index * 4}deg)` }"></div><div v-if="fireZone && layerVisibility.fire" class="fire-zone-ring" :style="{ left: fireZone.x, top: fireZone.y, width: fireZone.size }" :title="`火情等效范围 ${Math.round(Math.sqrt(Math.PI * (analysisResult?.fire_assessment?.fire_area_m2 || 0)))}m`"><span class="fire-zone-label">火区 ≈ {{ formatNumber(analysisResult?.fire_assessment?.fire_area_m2 || 0) }} m²</span></div><svg v-if="evacuationOverlay && layerVisibility.evacuation" class="evacuation-overlay" viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="疏散路线"><polyline :points="evacuationOverlay.points" class="evacuation-line"/></svg><div v-if="evacuationOverlay && layerVisibility.evacuation" class="map-node evacuation-exit" :style="{ left: evacuationOverlay.exit.x, top: evacuationOverlay.exit.y }"><span>出口 · 约 {{ evacuationOverlay.minutes }} 分钟</span></div><div v-for="marker in mapMarkers" :key="marker.id" :class="['map-node', marker.type, marker.waterType ? 'wt-' + waterTypeClass(marker.waterType) : '', { 'map-node-preferred': marker.preferred, 'map-node-active': activeMarker && activeMarker.id === marker.id, 'map-node-hover': hoveredDroneId === marker.id || hoveredWaterId === marker.id, 'map-node-pulse': focusPulse === marker.id }]" :style="{ left: marker.x, top: marker.y }" :title="marker.title || marker.label" @click.stop="selectMarker(marker)"><svg v-if="marker.type === 'drone'" class="node-quad" viewBox="0 0 40 40" :style="{ color: SUBGROUP_COLORS[marker.sub] || '#2563eb' }"><circle class="nq-track" cx="20" cy="20" r="15.5"/><circle class="nq-arc" cx="20" cy="20" r="15.5" transform="rotate(-90 20 20)" :stroke-dasharray="quadDash(marker.soc)"/><path class="nq-arms" d="M13 13 L27 27 M27 13 L13 27"/><circle class="nq-body" cx="20" cy="20" r="5"/></svg><component v-else :is="marker.icon" :size="17" :fill="marker.type === 'fire' ? 'currentColor' : undefined" /><span>{{ marker.label }}</span></div>

        <div class="map-compass">N</div>
        <div class="map-controls" role="group" aria-label="地图缩放控制"><button type="button" title="放大地图" aria-label="放大地图" @click="zoomMap(0.2)">+</button><button type="button" title="缩小地图" aria-label="缩小地图" @click="zoomMap(-0.2)">−</button><button type="button" title="重置地图视图" aria-label="重置地图视图" @click="resetMapView"><RefreshCw :size="14" /></button><output aria-live="polite">{{ Math.round(mapZoom * 100) }}%</output></div>
        <div class="map-scale" aria-label="比例尺"><i :style="{ width: mapScale.width }"></i><b>{{ mapScale.label }}</b></div>
      </div>
      </div>
      <div v-if="activeMarker" class="marker-detail" :style="activeMarker.style" role="dialog" :aria-label="activeMarker.title">
<div class="marker-detail-head"><b>{{ activeMarker.title }}</b><button class="marker-detail-close" aria-label="关闭详情" @click.stop="activeMarker = null">×</button></div>
<div class="marker-detail-body"><div v-for="row in activeMarker.rows" :key="row.k" class="marker-detail-row"><span>{{ row.k }}</span><b>{{ row.v }}</b></div></div>
</div>
      <div v-if="amapReady && mapMode === '2d'" class="map-coords" aria-live="polite" aria-label="光标经纬度"><Crosshair :size="13" /> <template v-if="cursorCoords">{{ cursorCoords.longitude.toFixed(6) }}°E · {{ cursorCoords.latitude.toFixed(6) }}°N</template><template v-else>移动鼠标读取经纬度</template></div>
      </div>
      <EvolutionChart :rounds="activeRounds" /></div>
      <aside class="map-side-rail" aria-label="态势信息栏">
        <div class="stream-panel" aria-label="协作与事件流"><div class="stream-head"><b>{{ streamMode === 'agent' ? '协作流' : '事件流' }}</b><span class="stream-tabs"><button :class="['stream-tab', { on: streamMode === 'agent' }]" :aria-pressed="streamMode === 'agent'" @click.stop="streamMode = 'agent'">协作</button><button :class="['stream-tab', { on: streamMode === 'events' }]" :aria-pressed="streamMode === 'events'" @click.stop="streamMode = 'events'">事件</button></span><small>{{ streamMode === 'agent' ? agentMessages.length + ' 条' : logs.length + ' 条' }}</small></div><div v-if="streamMode === 'agent'" class="stream-rows"><div v-if="!agentMessages.length" class="stream-empty">启动研判后，指挥官建案 / 侦察发现 / 方案提案 / 每轮自主研判等六角色协作消息将实时滚动显示。</div><div v-for="message in agentMessages.slice(-30).reverse()" :key="'am' + message.seq" class="stream-row stream-agent-row"><span class="stream-time">{{ (message.ts || '').slice(11, 19) }}</span><div class="stream-agent-body"><div class="stream-agent-head"><span class="agent-chip" :class="'mt-' + message.msg_type">{{ agentMsgLabel(message.msg_type) }}</span><small :class="'src-' + message.source">{{ agentSourceLabel(message.source) }}</small></div><p class="stream-content"><i>{{ message.frm }} → {{ message.to }}</i>{{ message.content }}</p></div></div></div><div v-else class="stream-rows"><div v-if="!logs.length" class="stream-empty">启动研判后，感知 / 研判 / 调度 / 监测事件将实时滚动显示。</div><div v-for="(log, index) in foldedLogs.slice(0, 30)" :key="log.message + log.timestamp + index" :class="['stream-row', { latest: index === 0 }]"><span class="stream-time">{{ logTime(log, index) }}</span><span class="stream-chip" :style="{ color: streamType(log).color, borderColor: streamType(log).color + '55' }">{{ streamType(log).label }}</span><span class="stream-text">{{ logText(log) }}</span><b v-if="log.repeat > 1" class="log-repeat">×{{ log.repeat }}</b></div></div></div>
        <div class="deploy-panel" aria-label="任务部署"><div class="deploy-head"><b>任务部署</b><small>{{ deploymentList.length }} 架 · {{ (analysisResult?.dispatch_plan?.selected_uavs || []).length }} 架出动</small></div><template v-for="group in deploymentGroups" :key="group.key"><div class="deploy-group-label" :style="{ color: SUBGROUP_COLORS[group.key] || '#8fa39a' }">{{ group.label }}</div><div class="deploy-rows"><div v-for="drone in group.rows" :key="drone.id" :class="['deploy-row', deployRowClass(drone)]" @mouseenter="hoveredDroneId = drone.id" @mouseleave="hoveredDroneId = ''" @click="focusDeployment(drone)" :title="'点击在地图上查看 ' + drone.id"><b>{{ drone.id }}</b><span>{{ drone.label }} · {{ drone.status }}</span><div class="deploy-soc"><i :class="drone.soc < 25 ? 'soc-low' : drone.soc < 50 ? 'soc-mid' : ''" :style="{ width: drone.soc + '%' }"></i></div><small>{{ drone.soc }}%</small><em v-if="missionPhaseText(drone.id) || (drone.task && drone.task !== '待命')">{{ missionPhaseText(drone.id) || drone.task }}</em></div></div></template></div>
        <div class="water-panel" aria-label="水源标注清单"><div class="water-panel-head"><b>水源标注</b><small>{{ waterSourcesList.length }} 处 · 按距离排序</small></div><div v-for="(water, index) in waterSourcesList.slice(0, 8)" :key="water.id" :class="['water-row', { preferred: water.preferred, linked: hoveredWaterId === water.id }]" @mouseenter="hoveredWaterId = water.id" @mouseleave="hoveredWaterId = ''" @click="onWaterRowClick(water)" :title="'点击查看水源详情'"><i class="water-dot" :class="'wt-' + waterTypeClass(water.type)"></i><b>{{ water.preferred ? '★ ' : '' }}{{ water.name }}</b><span>{{ water.type }} · {{ water.distance != null ? water.distance + 'm' : '距离未知' }}</span><small v-if="water.coordinates">{{ water.coordinates.longitude.toFixed(6) }}°E, {{ water.coordinates.latitude.toFixed(6) }}°N</small><small v-else>相对坐标</small></div><div v-if="!waterSourcesList.length" class="water-row"><span>当前环境无水源数据（可切换环境模式后刷新）</span></div></div>
        <div class="rail-terrain">
          <div class="terrain-data"><span>海拔 <b>{{ terrainVisual.elevation }} m</b></span><span>坡度 <b>{{ terrainVisual.slope }}°</b></span><span>来源 <b>{{ environmentSource }}</b></span></div>
          <div class="slope-badge"><span>坡向</span><b>{{ terrainVisual.upslope }} ↗</b><i></i><b>{{ terrainVisual.downslope }} ↘</b></div>
          <div class="wind-legend"><Wind :size="18" /><span>{{ result.environment.wind_direction || '—' }}风 · {{ result.environment.wind_speed ?? '—' }} m/s · {{ environmentSource }}</span></div>
        </div>
      </aside></div>
      <div class="map-statusbar"><span class="map-source" :class="{ fallback: !contourData }">{{ contourLoading ? '等高线加载中' : `等高线来源 · ${contourData?.source || '合成回退'}` }}</span><span>等高距 {{ contourData?.interval_m ?? terrainVisual.contourStep }} m</span><span>火点基准 {{ fireGpsLabel || '—' }}</span></div></section>

      <section v-else-if="viewTab === 'agents'" class="detail-view"><div class="detail-heading"><div><h2>Agent 协作</h2><p>指挥官 · 侦察研判 · 灭火调度 · 支援保障 · 仿真评估 · 交互审批 的实时协作消息流（黑板协议，可回放）。</p></div><span class="status-tag" :class="llmInfo?.available ? '' : 'orange'">{{ llmInfo?.available ? 'GLM 在线研判' : 'LLM 离线 · 确定性降级' }}</span></div><div class="full-logs agent-timeline"><div v-if="!agentMessages.length" class="empty-hint"><b>暂无协作消息</b>启动研判或演训模拟后，指挥官建案、侦察发现、方案提案与每轮自主研判会实时显示在这里。</div><div v-for="message in agentMessages" :key="message.seq" class="agent-msg"><span class="log-time">{{ message.ts?.slice(11) || message.ts }}</span><b class="agent-chip" :class="'mt-' + message.msg_type">{{ agentMsgLabel(message.msg_type) }}</b><div class="agent-msg-body"><strong>{{ message.frm }} → {{ message.to }}</strong><p>{{ message.content }}</p></div><small class="agent-source" :class="'src-' + message.source">{{ agentSourceLabel(message.source) }}</small></div></div></section>

      <section v-else-if="viewTab === 'history'" class="detail-view"><div class="detail-heading"><div><h2>历史任务</h2><p>任务记录来自后端 /api/analyzes，点击任务可恢复主显示结果。{{ historyTasks.length > 50 ? " 最近 50 条优先显示" : "" }}</p></div><button class="outline-btn" @click="loadHistory"><RefreshCw :size="14" /> 刷新</button></div><div class="full-logs"><div v-if="historyLoading"><div class="skeleton-row"></div><div class="skeleton-row"></div><div class="skeleton-row"></div></div><div v-else-if="!historyTasks.length" class="empty-hint"><b>还没有历史任务</b>点击右上角「开始任务」上传影像，完成研判后任务会自动归档到这里。</div><div v-for="task in historyTasks.slice(0, 50)" :key="task.analysis_id" class="history-row" @click="selectHistoryTask(task)"><span class="log-time">{{ task.created_at?.slice(0, 19).replace('T', ' ') }}</span><i></i><span><strong>{{ task.analysis_id }}</strong> · {{ task.input?.image_name || '未命名影像' }}</span><small>{{ task.status }}</small></div></div></section>

      <section v-else class="detail-view"><div class="detail-heading"><div><h2>任务日志</h2><p>记录当前演示任务的输入、分析阶段和调度决策。</p></div><span class="status-tag"><Activity :size="14" /> {{ logs.length }} 条记录</span></div><div class="full-logs"><div v-for="(log, index) in foldedLogs" :key="log.message + log.timestamp + index"><span class="log-time">{{ logTime(log, index) }}</span><i :class="{ bright: index === 0 }"></i><span>{{ logText(log) }} <small v-if="typeof log === 'object'">· {{ log.stage }} / {{ log.source }}</small></span><b v-if="log.repeat > 1" class="log-repeat">×{{ log.repeat }}</b><small>{{ index === 0 ? 'LATEST' : 'EVENT' }}</small></div></div></section>
    </main>
  </div>
</template>
