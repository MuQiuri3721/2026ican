<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
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
const approvalBusy = ref(false)
const environmentLoading = ref(false)
const environmentMode = ref('real')
const environmentCoordinates = ref({ latitude: 32.1256451, longitude: 118.9584748 })
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
const monitorResult = ref(null)
const rounds = ref([])
const serviceOnline = ref(false)
const projectStatus = ref({ framework: 'checking', demo_pipeline: 'checking', yolo: 'pending', vlm: 'pending', geo_data: 'demo-data' })
const logs = ref([
  { timestamp: '', stage: 'system', source: 'local', message: '系统已连接 · 等待新的侦察数据' },
  { timestamp: '', stage: 'scene', source: 'local', message: '场景「青龙山演示林区」已载入' },
  { timestamp: '', stage: 'fleet', source: 'local', message: '三架无人机状态同步完成' },
])

const scene = {
  id: 'forest-demo-01',
  name: '紫金山侦察区',
  incident: '北坡火情 · 初始研判',
  coordinates: '118.9584748°E · 32.1256451°N',
  windSpeed: 6.5,
  windDirection: '西北',
  altitude: 320,
  terrain: '丘陵',
  waterDistance: 800,
}

const drones = ref([
  { id: 'DR-01', label: '侦察蜂', role: 'RECON', battery: 82, status: '执行中', color: 'blue', task: '持续侦察' },
  { id: 'DR-02', label: '灭火蜂', role: 'SUPPRESSION', battery: 75, status: '待命', color: 'orange', task: '主力灭火' },
  { id: 'DR-03', label: '支援蜂', role: 'SUPPORT', battery: 91, status: '待命', color: 'green', task: '水源补给' },
])

const fallbackResult = {
  analysis_id: 'analysis-demo-001',
  fire_assessment: { level: 2, label: 'Ⅱ级 · 中等火情', fire_area_m2: 1800, smoke_area_m2: 4200, confidence: 0.91, spread_direction: '西北' },
  environment: { wind_speed: 6.5, wind_direction: '西北', altitude: 320, terrain: '丘陵', nearest_water_distance_m: 800 },
  dispatch_plan: {
    can_control: true,
    recommended_material: 'water',
    material_amount: 80,
    estimated_minutes: 18,
    tasks: [
      { drone_id: 'DR-01', task: '持续侦察' },
      { drone_id: 'DR-02', task: '主力灭火' },
      { drone_id: 'DR-03', task: '水源补给' },
    ],
  },
  explanation: '当前为中等火情，西北风可能推动火势向西北扩散。建议 DR-02 立即压制火线，DR-03 前往 800m 外水源点补给。',
}

const result = computed(() => {
  const base = analysisResult.value || fallbackResult
  if (!environment.value) return base
  return { ...base, environment: { ...base.environment, ...environment.value } }
})
const statusLabels = { succeeded: '已完成', completed: '已完成', running: '执行中', action_required: '需要处置', failed: '失败', queued: '排队中', available: '待命', assigned: '已分配', flying: '飞行中', working: '作业中', returning: '返航中', servicing: '维护中', charging: '充电中', fault: '故障', offline: '离线' }
const displayStatus = computed(() => statusLabels[analysisEnvelope.value?.status] || analysisEnvelope.value?.status || taskStatus.value)
const plan = computed(() => result.value.dispatch_plan || {})
const planStatus = computed(() => analysisEnvelope.value?.status || (plan.value.feasibility === false ? 'awaiting_confirmation' : 'ready'))
const resourceGap = computed(() => plan.value.resource_gap || result.value.resource_gap || [])
const peopleRisk = computed(() => peopleStatus.value === 'unknown' ? '人员情况不确定：禁止低空近距离作业，需先确认现场是否有人。' : peopleStatus.value === 'confirmed' ? '有人风险：已启用人员避让与人工复核，禁止自动投放。' : '已确认无人：仍需保持通信与撤离通道。')
const activeRounds = computed(() => rounds.value.length ? rounds.value : (analysisEnvelope.value?.rounds || []))
const latestRound = computed(() => activeRounds.value.at(-1))
const monitorArea = computed(() => monitorResult.value?.next_fire_area_m2 ?? result.value.fire_assessment.fire_area_m2)
const dataMode = computed(() => result.value.data_mode || '本地演示数据 · 规则引擎')
const metrics = computed(() => [
  { label: '火焰面积', value: formatNumber(result.value.fire_assessment.fire_area_m2), unit: 'm²', change: '+12.4%', tone: 'orange', icon: Flame },
  { label: '烟雾覆盖', value: formatNumber(result.value.fire_assessment.smoke_area_m2), unit: 'm²', change: '+8.1%', tone: 'slate', icon: CloudRain },
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
  const coordinateText = coordinates ? `${coordinates.longitude.toFixed(5)}°E, ${coordinates.latitude.toFixed(5)}°N` : relativePoint(water) ? `相对 ${Math.round(relativePoint(water).x)}, ${Math.round(relativePoint(water).y)}` : '坐标缺失'
  return `${waterTypeLabel(water)} · ${water?.name || '未命名'} · ${distanceText} · ${coordinateText}`
}

const mapRoutes = computed(() => {
  const roads = environment.value?.road_context
  return roads?.routes || roads?.nodes || (roads?.nearest_transport ? [roads.nearest_transport] : [])
})
const mapMarkers = computed(() => {
  const waters = Array.isArray(environment.value?.water_sources) ? environment.value.water_sources : []
  const road = environment.value?.road_context?.nearest_transport || environment.value?.road_context?.nearest_vehicle_access_candidate
  const waterMarkers = waters.map((water, index) => {
    const position = markerPosition(water)
    return position ? { id: `water-${water.id || water.name || index}`, type: 'water', label: waterLabel(water), icon: Droplets, ...position } : null
  }).filter(Boolean)
  const roadPosition = markerPosition(road)
  return [
    { id: 'fire', type: 'fire', label: '火点中心', icon: Flame, x: '50%', y: '50%' },
    ...waterMarkers,
    ...(road && roadPosition ? [{ id: 'road', type: 'road', label: `${road.name || '最近道路'} · ${road.distance_m ?? '—'}m`, icon: MapPinned, ...roadPosition }] : []),
    ...drones.value.map((drone, index) => { const position = markerPosition(drone); return { id: drone.id, type: 'drone', label: `${drone.id}${position ? '' : ' · 演示位置'}`, icon: Radio, ...(position || { x: `${15 + (index % 5) * 17}%`, y: `${22 + Math.floor(index / 5) * 35}%` }) } }),
  ]
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
    { label: '水源', value: water ? `${water.name || '未命名水源'} · ${water.distance_m ?? '—'}m · ${water.latitude ?? '—'}, ${water.longitude ?? '—'}` : '暂无', tone: 'blue' },
    { label: '道路', value: road ? `${road.name || '未命名道路'} · ${road.distance_m ?? '—'}m · ${road.nearest_point?.latitude ?? '—'}, ${road.nearest_point?.longitude ?? '—'}` : '暂无', tone: 'orange' },
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
    const query = new URLSearchParams({ scene_id: scene.id, latitude: String(latitude), longitude: String(longitude), environment_mode: environmentMode.value, water_radius_m: '3000', road_radius_m: '3000' })
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
    const query = new URLSearchParams({ latitude: String(latitude), longitude: String(longitude), radius_deg: '0.04', interval_m: '20', max_points: '180' })
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

function formatNumber(value) {
  return new Intl.NumberFormat('zh-CN').format(value)
}

function selectNav(id) {
  activeTab.value = id
  if (id === 'command') viewTab.value = 'overview'
}

function selectView(id) {
  viewTab.value = id
  if (id === 'monitor') activeTab.value = 'map'
  else if (id === 'history') activeTab.value = 'logs'
  else if (id === 'overview') activeTab.value = 'command'
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

function selectHistoryTask(task) {
  if (!task?.analysis_id) return
  applyEnvelope(task)
  monitorResult.value = task.result?.monitor || null
  currentStage.value = task.stages?.at(-1)?.stage || task.stages?.at(-1)?.name || '历史任务已恢复'
  if (Array.isArray(task.stages)) stages.value = task.stages
  if (Array.isArray(task.result?.fleet)) updateDrones(task.result)
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
    return { ...drone, id, role, battery: Number(drone.battery ?? drone.soc ?? 0), status, label: drone.label || (role === 'reconnaissance' ? '侦察蜂' : role === 'firefighting' ? '灭火蜂' : '支援蜂'), color: drone.color || (role === 'reconnaissance' ? 'blue' : role === 'firefighting' ? 'orange' : 'green'), task: payload.dispatch_plan?.tasks?.find((task) => task.drone_id === id)?.task || drone.assigned_task || '待命' }
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

async function submitApproval(action) {
  if (!analysisId.value || approvalBusy.value) return
  approvalBusy.value = true
  try {
    const response = await fetch(`/api/tasks/${analysisId.value}/approval`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, plan_id: plan.value.plan_id, constraints: { people_status: peopleStatus.value } }) })
    if (!response.ok) throw new Error('方案操作失败')
    applyEnvelope(await response.json())
    addLog(`方案操作完成 · ${action}`)
  } catch (error) { errorMessage.value = '方案操作失败，请重试。'; console.warn(error) } finally { approvalBusy.value = false }
}

function fleetForPayload() { return drones.value.map((drone) => ({ ...drone, soc: drone.soc ?? drone.battery })) }


function applyEnvelope(payload) {
  const envelope = payload?.payload || payload
  analysisEnvelope.value = envelope
  analysisId.value = envelope?.analysis_id || ''
  analysisResult.value = envelope?.result || null
  stages.value = Array.isArray(envelope?.stages) ? envelope.stages : []
  taskStatus.value = statusLabels[envelope?.status] || envelope?.status || '待命'
  currentStage.value = stages.value.at(-1)?.stage || stages.value.at(-1)?.name || currentStage.value
  updateDrones(analysisResult.value)
  if (analysisResult.value?.environment) environment.value = analysisResult.value.environment
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
    const response = await fetch('/api/analyzes')
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

async function loadServiceStatus() {
  try {
    const [healthResponse, statusResponse] = await Promise.all([fetch('/api/health'), fetch('/api/project-status')])
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

function acceptFile(file) {
  errorMessage.value = ''
  if (!file) return
  const allowed = ['image/jpeg', 'image/png', 'video/mp4']
  if (!allowed.includes(file.type)) {
    errorMessage.value = '仅支持 JPG、PNG 或 MP4 文件。'
    return
  }
  if (file.size > 200 * 1024 * 1024) {
    errorMessage.value = '文件大小不能超过 200MB。'
    return
  }
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  selectedFile.value = file
  previewUrl.value = URL.createObjectURL(file)
  uploaded.value = true
  progress.value = 0
  addLog(`已接收新航拍影像 · ${file.name}`)
}

function handleFileChange(event) {
  acceptFile(event.target.files?.[0])
  event.target.value = ''
}

function handleDrop(event) {
  acceptFile(event.dataTransfer.files?.[0])
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
    formData.append('scene_id', scene.id)
    formData.append('use_vlm', 'false')
    const { latitude, longitude } = environmentForPayload()
    formData.append('latitude', String(latitude))
    formData.append('longitude', String(longitude))
    formData.append('environment_mode', environmentMode.value)
    formData.append('water_search_radius_m', '3000')
    formData.append('road_search_radius_m', '3000')
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

async function runMonitor() {
  if (!analysisId.value || monitoring.value) return
  const monitoredId = analysisId.value
  monitoring.value = true
  try {
    const response = await fetch(`/api/monitor/${monitoredId}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ elapsed_minutes: 5, extinguishing_liters: 40, fleet_snapshot: fleetForPayload(), inventory: inventory.value }) })
    if (!response.ok) throw new Error('监测接口不可用')
    const payload = await response.json()
    if (monitoredId !== analysisId.value) return
    const envelope = payload?.payload || payload
    const updatedResult = envelope?.result || null
    monitorResult.value = updatedResult?.monitor || payload?.monitor || payload
    rounds.value = Array.isArray(envelope?.rounds) ? envelope.rounds : rounds.value
    analysisEnvelope.value = envelope
    analysisId.value = envelope?.analysis_id || monitoredId
    analysisResult.value = updatedResult
    stages.value = Array.isArray(envelope?.stages) ? envelope.stages : stages.value
    taskStatus.value = statusLabels[envelope?.status] || envelope?.status || '执行中'
    currentStage.value = stages.value.at(-1)?.stage || stages.value.at(-1)?.name || '闭环监测完成'
    updateDrones(updatedResult)
    const action = payload?.action || monitorResult.value?.action || '保持观察'
    addLog(`第 ${envelope?.monitor_round || activeRounds.value.length + 1} 轮监测完成 · 下一步：${action} · ${monitorResult.value?.reason || '无重规划原因'}`, { stage: 'monitor', source: 'rules' })
    await loadEvents(monitoredId)
  } catch (error) {
    if (monitoredId === analysisId.value) {
      errorMessage.value = '监测服务暂不可用。'
      addLog('闭环监测失败 · 保持当前任务状态')
    }
  } finally {
    monitoring.value = false
  }
}

function resetAnalysis() {
  analysisEnvelope.value = null
  analysisResult.value = null
  analysisId.value = ''
  stages.value = []
  currentStage.value = '等待影像接入'
  rounds.value = []
  selectedFile.value = null
  uploaded.value = false
  progress.value = 0
  errorMessage.value = ''
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
  addLog('已清空当前影像 · 等待新的侦察数据')
}

onBeforeUnmount(() => {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})

onMounted(() => {
  loadServiceStatus()
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

    <main>
      <header><div><div class="breadcrumb">COMMAND CENTER <span>/</span> {{ activeTab.toUpperCase() }}</div><h1>森林火灾救援工作台</h1><p>多源感知 · 智能研判 · 集群调度 · 闭环处置</p></div><div class="header-actions"><button class="icon-btn" title="查看通知"><Bell :size="18" /><i></i></button><div class="utc">UTC+08:00<br><strong>2026.09.02</strong></div></div></header>
      <section class="toolbar"><div class="tab-pills" role="tablist" aria-label="任务视图"><button :class="{ selected: viewTab === 'overview' }" @click="selectView('overview')">任务概览</button><button :class="{ selected: viewTab === 'monitor' }" @click="selectView('monitor')">实时监测</button><button :class="{ selected: viewTab === 'history' }" @click="selectView('history')">历史任务</button></div><div class="toolbar-right"><span class="task-badge">任务状态 · {{ displayStatus }}</span><span class="sync"><span class="live-dot"></span> {{ currentStage }}</span><button class="primary" :disabled="analyzing" @click="startAnalysis"><Bot :size="17" /> {{ analyzing ? '分析中…' : '启动智能研判' }}</button></div></section>
      <div v-if="errorMessage" class="notice" role="status"><Activity :size="16" /><span>{{ errorMessage }}</span><button class="notice-close" title="关闭提示" @click="errorMessage = ''">×</button></div>

      <div v-if="activeTab === 'command'" class="dashboard">
        <section class="hero-panel"><div class="panel-heading"><div><span class="section-kicker">ACTIVE INCIDENT · FF-20260902-001</span><h2>{{ scene.incident }}</h2></div><span class="severity"><span></span>{{ result.fire_assessment.label }}</span></div><div class="map-preview"><div class="map-grid"></div><div class="ridge ridge-a"></div><div class="ridge ridge-b"></div><div class="fire-zone"><span class="pulse"></span><Flame :size="23" fill="currentColor" /><label>火点中心<br><b>{{ scene.coordinates }}</b></label></div><div class="wind-arrow"><Wind :size="20" /><span>{{ result.environment.wind_direction || '—' }} {{ result.environment.wind_speed ?? '—' }} m/s</span></div><div class="map-label top">北坡林区 / ZONE A</div><div class="map-label bottom">{{ result.environment.nearest_water?.distance_m ?? result.environment.nearest_water_distance_m ?? '—' }}m · {{ result.environment.nearest_water?.name || '最近水源' }}</div></div><div class="hero-footer"><div><small>当前处置结论</small><strong>{{ result.dispatch_plan.can_control ? '可控制 · 建议立即出动' : '暂不可控 · 请求增援' }}</strong></div><div class="hero-stat"><small>预计处置时间</small><strong>{{ result.dispatch_plan.estimated_minutes }} <em>MIN</em></strong></div><div class="hero-stat"><small>下次评估</small><strong>05 <em>MIN</em></strong></div></div></section>

        <section class="upload-panel"><div class="panel-heading"><div><span class="section-kicker">INPUT CHANNEL</span><h2>现场影像接入</h2></div><FileImage :size="19" class="muted-icon" /></div><input ref="fileInput" class="visually-hidden" type="file" accept="image/jpeg,image/png,video/mp4" @change="handleFileChange"><div class="dropzone" :class="{ uploaded }" @click="openFilePicker" @dragover.prevent @drop.prevent="handleDrop"><div v-if="previewUrl && selectedFile?.type.startsWith('image/')" class="preview-thumb"><img :src="previewUrl" alt="已选择的火灾影像预览"></div><div v-else class="upload-orb"><Upload :size="22" /></div><strong>{{ uploaded ? '影像已接入' : '拖入航拍图像或视频' }}</strong><span>{{ uploaded ? `${selectedFile.name} · ${(selectedFile.size / 1024 / 1024).toFixed(1)} MB` : '支持 JPG / PNG / MP4 · 最大 200MB' }}</span><button type="button" @click.stop="openFilePicker">{{ uploaded ? '更换文件' : '选择文件' }}</button></div><div class="process"><div class="process-row"><span>分析管线</span><b>{{ progress }}%</b></div><div class="progress"><i :style="{ width: progress + '%' }"></i></div><div class="pipeline"><span :class="{ done: progress >= 24 }">视觉识别</span><ChevronRight :size="13" /><span :class="{ done: progress >= 48 }">环境融合</span><ChevronRight :size="13" /><span :class="{ done: progress >= 72 }">风险评估</span><ChevronRight :size="13" /><span :class="{ done: progress >= 90 }">调度生成</span></div><div class="model-status"><span>YOLO <b>{{ projectStatus.yolo === 'pending' ? '待接入' : '在线' }}</b></span><span>VLM <b>{{ projectStatus.vlm === 'pending' ? '待接入' : '在线' }}</b></span><span>场景数据 <b>固定演示</b></span></div></div><button v-if="uploaded" class="reset-link" @click="resetAnalysis"><RefreshCw :size="13" /> 清空并重新接入</button></section>

        <section class="environment-panel panel"><div class="panel-heading"><div><span class="section-kicker">ENVIRONMENT FEED</span><h2>现场环境</h2></div><button class="outline-btn environment-refresh" :disabled="environmentLoading" @click="loadEnvironment"><RefreshCw :size="14" /> {{ environmentLoading ? '刷新中…' : '刷新环境' }}</button></div><div class="environment-controls"><label>模式 <select v-model="environmentMode" @change="loadEnvironment"><option value="real">真实数据</option><option value="auto">自动</option><option value="offline">离线演示（不联网）</option><option value="demo">演示数据</option></select></label><div class="coordinate-editor"><label>纬度 <input v-model="coordinateDraft.latitude" inputmode="decimal" aria-label="纬度"></label><label>经度 <input v-model="coordinateDraft.longitude" inputmode="decimal" aria-label="经度"></label><button class="outline-btn" type="button" @click="applyCoordinates">应用</button></div><span>{{ environmentCoordinates.latitude.toFixed(7) }}, {{ environmentCoordinates.longitude.toFixed(7) }}</span></div><div v-if="coordinateError" class="coordinate-error" role="alert">{{ coordinateError }}</div><div class="environment-meta"><span>采集 · {{ environment?.collected_at?.slice(0, 19).replace('T', ' ') || '等待刷新' }}</span><span>状态 · {{ environmentStatus }}</span><span>来源 · {{ environmentSource }}</span><span v-if="environmentStale">stale / 缓存</span><span v-if="environmentFallback">fallback · {{ environmentFallback }}</span></div><div class="environment-grid"><div v-for="item in environmentFeatures" :key="item.label" class="environment-item"><span>{{ item.label }}</span><strong :class="'tone-' + item.tone">{{ item.value }}</strong></div></div></section>
        <section class="metrics-grid"><article v-for="metric in metrics" :key="metric.label" class="metric-card"><div class="metric-top"><span>{{ metric.label }}</span><component :is="metric.icon" :size="17" :class="'tone-' + metric.tone" /></div><div class="metric-value">{{ metric.value }} <small>{{ metric.unit }}</small></div><div :class="['metric-change', 'tone-' + metric.tone]">{{ metric.change }}</div></article></section>
        <section class="fleet-panel panel"><div class="panel-heading"><div><span class="section-kicker">FLEET STATUS</span><h2>无人机集群状态</h2></div><button class="text-btn" @click="selectNav('fleet')">查看详情 <ChevronRight :size="14" /></button></div><div class="fleet-list"><div v-for="drone in drones" :key="drone.id" class="drone-row"><div :class="['drone-icon', drone.color]"><Zap :size="17" /></div><div class="drone-name"><strong>{{ drone.id }} <span>{{ drone.label }}</span></strong><small>{{ drone.role }}</small></div><div class="battery"><div class="battery-bar"><i :style="{ width: drone.battery + '%' }"></i></div><span>{{ drone.battery }}%</span></div><span :class="['drone-status', drone.status === '执行中' ? 'active-status' : '']"><i></i>{{ drone.status }}</span></div></div></section>
        <section class="decision-panel panel"><div class="panel-heading"><div><span class="section-kicker">AGENT DECISION</span><h2>调度建议</h2></div><span class="ai-badge"><Bot :size="14" /> {{ dataMode }}</span></div><div class="decision-callout"><div class="decision-icon"><Gauge :size="20" /></div><div><strong>{{ result.dispatch_plan.can_control ? '建议立即启动一级处置响应' : '建议立即请求增援' }}</strong><p>{{ result.explanation }}</p></div></div><div class="plan-summary" v-if="analysisEnvelope?.status === 'awaiting_confirmation'"><b>方案待确认</b><span>主方案：{{ plan.plan_id || '当前方案' }}</span><span>备选：{{ plan.alternative_plan?.length ? `${plan.alternative_plan.length} 个` : '暂无' }}</span><span>时间区间：{{ plan.estimated_control_time?.min ?? plan.estimated_minutes ?? '—' }}–{{ plan.estimated_control_time?.max ?? plan.estimated_minutes ?? '—' }} 分钟</span><span>资源缺口：{{ resourceGap.length ? resourceGap.map((gap) => gap.name || gap.resource || gap.type).join('、') : '无' }}</span></div><div class="people-risk"><label>人员状态 <select v-model="peopleStatus"><option value="confirmed">有人</option><option value="absent">无人</option><option value="unknown">不确定</option></select></label><span>{{ peopleRisk }}</span></div><div class="approval-actions" v-if="analysisId"><button class="outline-btn" :disabled="approvalBusy" @click="submitApproval('approve')">批准主方案</button><button class="outline-btn" :disabled="approvalBusy" @click="submitApproval('adjust')">调整方案</button><button class="outline-btn danger-btn" :disabled="approvalBusy" @click="submitApproval('reject')">驳回</button><button class="outline-btn danger-btn" :disabled="approvalBusy" @click="submitApproval('terminate')">终止任务</button></div><div class="task-chips"><span v-for="task in result.dispatch_plan.tasks" :key="task.drone_id"><b>{{ task.drone_id }}</b> {{ task.task }}</span></div><button v-if="analysisResult" class="monitor-btn" :disabled="monitoring" @click="runMonitor"><RefreshCw :size="14" /> {{ monitoring ? '监测中…' : '执行下一轮监测' }}</button><div v-if="monitorResult" class="monitor-result">第 {{ analysisEnvelope?.monitor_round || activeRounds.length }} 轮 · 监测结果：火焰面积 {{ monitorArea }}m² · FLP {{ monitorResult.fire_load_flp ?? monitorResult.next_fire_load_flp ?? '—' }} · SOC {{ monitorResult.next_fleet?.map((drone) => `${drone.id}:${drone.soc ?? drone.battery}%`).join('、') || '—' }} · 库存 {{ monitorResult.next_inventory ? JSON.stringify(monitorResult.next_inventory) : '—' }} · {{ monitorResult.reason || '无重规划原因' }}</div></section>
        <section class="log-panel panel"><div class="panel-heading"><div><span class="section-kicker">SYSTEM ACTIVITY</span><h2>任务日志</h2></div><span class="log-count">{{ logs.length }} EVENTS</span></div><div class="logs"><div v-for="(log, index) in logs.slice(0, 6)" :key="log.message + log.timestamp + index"><span class="log-time">{{ logTime(log, index) }}</span><i :class="{ bright: index === 0 }"></i><span>{{ logText(log) }} <small v-if="typeof log === 'object'">· {{ log.stage }} / {{ log.source }}</small></span></div></div></section>
      </div>

      <section v-else-if="activeTab === 'fleet'" class="detail-view"><div class="detail-heading"><div><span class="section-kicker">FLEET OPERATIONS</span><h2>无人机集群</h2><p>当前集群共有 {{ drones.length }} 架无人机，状态数据来自 /api/fleet。</p></div><span class="status-tag"><span class="live-dot"></span> 全部在线</span></div><div class="fleet-detail-grid"><article v-for="drone in drones" :key="drone.id" class="fleet-detail-card"><div :class="['drone-icon large', drone.color]"><Zap :size="20" /></div><div class="fleet-detail-title"><strong>{{ drone.id }}</strong><span>{{ drone.label }}</span></div><div class="fleet-detail-role">{{ drone.role }}</div><div class="detail-battery"><div class="battery-bar"><i :style="{ width: drone.battery + '%' }"></i></div><strong>{{ drone.battery }}%</strong></div><div class="fleet-detail-task"><span>当前任务</span><b>{{ drone.task }}</b></div><button class="outline-btn" @click="addLog(`${drone.id} 状态详情已查看`)"><ListFilter :size="14" /> 查看状态</button></article></div></section>

      <section v-else-if="activeTab === 'map'" class="detail-view map-view"><div class="detail-heading"><div><span class="section-kicker">GEO SITUATION</span><h2>林区态势</h2><p>基于环境接口的局部相对态势示意 · 海拔 {{ environment?.terrain?.elevation_m ?? environment?.altitude ?? '—' }}m</p></div><span class="status-tag orange"><MapPinned :size="14" /> {{ environmentCoordinates.longitude.toFixed(7) }}°E · {{ environmentCoordinates.latitude.toFixed(7) }}°N</span></div><div class="large-map" @wheel.prevent="handleMapWheel" @pointerdown="startMapDrag" @pointermove="moveMap" @pointerup="stopMapDrag" @pointercancel="stopMapDrag" @pointerleave="stopMapDrag"><div class="map-scene-layer" :class="{ dragging: mapDragging }" :style="mapLayerStyle"><div class="terrain-wash"></div><div class="map-grid"></div><svg class="terrain-svg" viewBox="0 0 1000 520" preserveAspectRatio="none" aria-label="紫金山局部相对俯视等高线示意图"><defs><pattern id="topoGrid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M 40 0 L 0 0 0 40" fill="none" stroke="#b7a9a0" stroke-width=".6" opacity=".42"/></pattern></defs><rect width="1000" height="520" fill="url(#topoGrid)"/><g class="contours"><g v-for="line in contourPaths" :key="line.d"><path class="contour-line" :class="{ 'major-contour': line.major }" :d="line.d"/><text v-if="line.major && line.elevation != null" class="contour-label" :x="line.labelX" :y="line.labelY">{{ line.elevation }} m</text></g></g><circle class="summit-ring" cx="560" cy="248" r="16"/><text class="summit-label" x="560" y="244" text-anchor="middle">峰顶</text><text class="summit-elevation" x="560" y="258" text-anchor="middle">{{ terrainVisual.elevation }} m</text></svg><div class="terrain-caption"><strong>紫金山 · 局部地形态势</strong><span>相对示意 · 非精确 GIS</span></div><div class="contour-note"><span>等高距</span><b>{{ contourData?.interval_m ?? terrainVisual.contourStep }} m</b><small>{{ contourData?.source || '合成等高线' }}</small></div><div class="slope-badge"><span>坡向</span><b>{{ terrainVisual.upslope }} ↗</b><i></i><b>{{ terrainVisual.downslope }} ↘</b></div><div v-for="(route, index) in mapRoutes" :key="route.name + index" class="route-line" :style="{ left: `${25 + index * 4}%`, top: `${48 + index * 3}%`, width: `${30 + (index % 3) * 8}%`, transform: `rotate(${-16 + index * 4}deg)` }"></div><div v-for="marker in mapMarkers" :key="marker.id" :class="['map-node', marker.type]" :style="{ left: marker.x, top: marker.y }"><component :is="marker.icon" :size="17" :fill="marker.type === 'fire' ? 'currentColor' : undefined" /><span>{{ marker.label }}</span></div><div class="map-compass">N</div></div><div class="map-controls" role="group" aria-label="地图缩放控制"><button type="button" title="放大地图" aria-label="放大地图" @click="zoomMap(0.2)">+</button><button type="button" title="缩小地图" aria-label="缩小地图" @click="zoomMap(-0.2)">−</button><button type="button" title="重置地图视图" aria-label="重置地图视图" @click="resetMapView"><RefreshCw :size="14" /></button><output aria-live="polite">{{ Math.round(mapZoom * 100) }}%</output></div><div class="map-source" :class="{ fallback: !contourData }">{{ contourLoading ? '等高线加载中' : `等高线来源 · ${contourData?.source || '合成回退'}` }}</div><div class="map-legend"><span><i class="legend-fire"></i>火点</span><span><i class="legend-water"></i>水源</span><span><i class="legend-road"></i>道路</span><span><i class="legend-drone"></i>无人机</span><span><i class="legend-contour"></i>等高线</span></div><div class="terrain-data"><span>海拔 <b>{{ terrainVisual.elevation }} m</b></span><span>坡度 <b>{{ terrainVisual.slope }}°</b></span><span>来源 <b>{{ environmentSource }}</b></span></div><div class="wind-legend"><Wind :size="18" /><span>{{ result.environment.wind_direction || '—' }}风 · {{ result.environment.wind_speed ?? '—' }} m/s · {{ environmentSource }}</span></div></div></section>

      <section v-else-if="viewTab === 'history'" class="detail-view"><div class="detail-heading"><div><span class="section-kicker">TASK ARCHIVE</span><h2>历史任务</h2><p>任务记录来自后端 /api/analyzes，点击任务可恢复主显示结果。</p></div><button class="outline-btn" @click="loadHistory"><RefreshCw :size="14" /> 刷新</button></div><div class="full-logs"><div v-if="historyLoading">正在加载历史任务…</div><div v-else-if="!historyTasks.length">暂无历史任务</div><div v-for="task in historyTasks" :key="task.analysis_id" class="history-row" @click="selectHistoryTask(task)"><span class="log-time">{{ task.created_at?.slice(0, 19).replace('T', ' ') }}</span><i></i><span><strong>{{ task.analysis_id }}</strong> · {{ task.input?.image_name || '未命名影像' }}</span><small>{{ task.status }}</small></div></div></section>

      <section v-else class="detail-view"><div class="detail-heading"><div><span class="section-kicker">SYSTEM ACTIVITY</span><h2>任务日志</h2><p>记录当前演示任务的输入、分析阶段和调度决策。</p></div><span class="status-tag"><Activity :size="14" /> {{ logs.length }} 条记录</span></div><div class="full-logs"><div v-for="(log, index) in logs" :key="log.message + log.timestamp + index"><span class="log-time">{{ logTime(log, index) }}</span><i :class="{ bright: index === 0 }"></i><span>{{ logText(log) }} <small v-if="typeof log === 'object'">· {{ log.stage }} / {{ log.source }}</small></span><small>{{ index === 0 ? 'LATEST' : 'EVENT' }}</small></div></div></section>
    </main>
  </div>
</template>
