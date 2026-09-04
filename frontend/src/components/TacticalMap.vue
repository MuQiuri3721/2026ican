<script setup>
// 真实卫星态势图：高德 AMap JS API 2.0（卫星俯视 + 中文路网）。
// 所有 WGS-84 数据（SRTM 等高线 / OSM 水源 / fire_origin_gps）打点前统一转 GCJ-02，
// 鼠标读数再近似反算回 WGS-84，与后端契约坐标一致。Key 缺失或加载失败时 emit fallback，
// 由父组件回退到等高线示意图，演示不因 Key 问题中断。
import { onBeforeUnmount, onMounted, shallowRef, watch } from 'vue'
import AMapLoader from '@amap/amap-jsapi-loader'

const props = defineProps({
  result: { type: Object, default: null },
  environment: { type: Object, default: null },
  drones: { type: Array, default: () => [] },
  waterList: { type: Array, default: () => [] },
  contours: { type: Object, default: null },
  layerVisibility: { type: Object, required: true },
  selectedUavs: { type: Array, default: () => [] },
  focusPulse: { type: String, default: '' },
  hoveredDroneId: { type: String, default: '' },
  hoveredWaterId: { type: String, default: '' },
  activeMarkerId: { type: String, default: '' },
  mission: { type: Object, default: null },
  defaultCenter: { type: Object, default: () => ({ latitude: 32.0725, longitude: 118.8415 }) },
})
const emit = defineEmits(['select-marker', 'coords', 'ready', 'fallback'])

const containerEl = shallowRef(null)
const map = shallowRef(null)
// AMap 命名空间只挂实例上，避免被 Vue 深响应式代理（官方 Vue3 建议 shallowRef）。
const AMapNS = shallowRef(null)
const layerOverlays = { fire: [], contour: [], water: [], drone: [], road: [], evacuation: [] }
const markerIndex = new Map()
let pulseTimer = null

// ---------- WGS-84 <-> GCJ-02（标准偏移算法，中国境外原样返回） ----------
const GCJ_A = 6378245.0
const GCJ_EE = 0.00669342162296594323
function outOfChina(lat, lng) {
  return lng < 72.004 || lng > 137.8347 || lat < 0.8293 || lat > 55.8271
}
function transformLat(x, y) {
  let ret = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x))
  ret += (20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2 / 3
  ret += (20 * Math.sin(y * Math.PI) + 40 * Math.sin(y / 3 * Math.PI)) * 2 / 3
  ret += (160 * Math.sin(y / 12 * Math.PI) + 320 * Math.sin(y * Math.PI / 30)) * 2 / 3
  return ret
}
function transformLng(x, y) {
  let ret = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x))
  ret += (20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2 / 3
  ret += (20 * Math.sin(x * Math.PI) + 40 * Math.sin(x / 3 * Math.PI)) * 2 / 3
  ret += (150 * Math.sin(x / 12 * Math.PI) + 300 * Math.sin(x / 30 * Math.PI)) * 2 / 3
  return ret
}
function wgs2gcj(lat, lng) {
  if (outOfChina(lat, lng)) return { lat, lng }
  let dLat = transformLat(lng - 105, lat - 35)
  let dLng = transformLng(lng - 105, lat - 35)
  const radLat = lat / 180 * Math.PI
  let magic = Math.sin(radLat)
  magic = 1 - GCJ_EE * magic * magic
  const sqrtMagic = Math.sqrt(magic)
  dLat = (dLat * 180) / ((GCJ_A * (1 - GCJ_EE)) / (magic * sqrtMagic) * Math.PI)
  dLng = (dLng * 180) / (GCJ_A / sqrtMagic * Math.cos(radLat) * Math.PI)
  return { lat: lat + dLat, lng: lng + dLng }
}
function gcj2wgs(lat, lng) {
  const approx = wgs2gcj(lat, lng)
  return { lat: lat * 2 - approx.lat, lng: lng * 2 - approx.lng }
}
// 米制偏移 → 经纬度（无人环/疏散网格等相对米制数据落图）
function offsetWgs(lat, lng, dxM, dyM) {
  return {
    latitude: lat + dyM / 111320,
    longitude: lng + dxM / (111320 * Math.cos(lat * Math.PI / 180)),
  }
}
function haversineM(lat1, lng1, lat2, lng2) {
  const rad = Math.PI / 180
  const dLat = (lat2 - lat1) * rad
  const dLng = (lng2 - lng1) * rad
  const s = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLng / 2) ** 2
  return 2 * 6371000 * Math.asin(Math.sqrt(s))
}

// ---------- 数据取值（与 App.vue 示意图同一套字段口径） ----------
function fireGps() {
  const gps = props.result?.scene?.fire_origin_gps
  if (gps && Number.isFinite(Number(gps.latitude)) && Number.isFinite(Number(gps.longitude))) {
    return { latitude: Number(gps.latitude), longitude: Number(gps.longitude) }
  }
  return props.defaultCenter
}
function fireRadiusM() {
  const area = Number(props.result?.fire_assessment?.fire_area_m2)
  if (!Number.isFinite(area) || area <= 0) return 60
  return Math.max(40, Math.sqrt(area / Math.PI))
}
function waterGps(item) {
  const lat = Number(item?.latitude ?? item?.coordinates?.latitude)
  const lng = Number(item?.longitude ?? item?.coordinates?.longitude)
  if (Number.isFinite(lat) && Number.isFinite(lng)) return { latitude: lat, longitude: lng }
  // demo 水源只有相对米制坐标：以火点为原点换算到真实经纬度
  const rel = item?.position && Number.isFinite(Number(item.position.x)) ? item.position : null
  if (rel) {
    const origin = fireGps()
    return offsetWgs(origin.latitude, origin.longitude, Number(rel.x) * 6, Number(rel.y) * 6)
  }
  return null
}
function preferredWaterItem() {
  const preferred = props.waterList.find((item) => item.preferred)
  return preferred || null
}

// ---------- 覆盖物渲染 ----------
function clearLayer(key) {
  if (map.value && layerOverlays[key].length) map.value.remove(layerOverlays[key])
  layerOverlays[key] = []
}
function clearAll() {
  for (const key of Object.keys(layerOverlays)) clearLayer(key)
  markerIndex.clear()
}
function addOverlay(key, overlay, meta) {
  map.value.add(overlay)
  layerOverlays[key].push(overlay)
  if (meta) {
    overlay.tmapMeta = meta
    markerIndex.set(meta.id, overlay)
  }
  if (!props.layerVisibility[key]) overlay.hide?.()
  return overlay
}
function percentOf(lngLat) {
  const px = map.value.lngLatToContainer(lngLat)
  const el = containerEl.value
  if (!el || !px) return { x: '50%', y: '50%' }
  const x = Math.max(3, Math.min(97, (px.getX() / el.offsetWidth) * 100))
  const y = Math.max(3, Math.min(97, (px.getY() / el.offsetHeight) * 100))
  return { x: `${x.toFixed(1)}%`, y: `${y.toFixed(1)}%` }
}
function markerPayload(id, type, label, lngLat) {
  const pos = percentOf(lngLat)
  return { id, type, label, ...pos }
}
// 需要悬停/选中/脉冲 class 联动的标记用真实 DOM 节点（字符串 content 拿不到节点引用）
function elt(className, html) {
  const node = document.createElement('div')
  node.className = className
  node.innerHTML = html
  return node
}

function contourColor(elevation, min, max) {
  const t = max > min ? (elevation - min) / (max - min) : 0.5
  // 低海拔暖沙色 → 高海拔亮米白，卫星影像上保持可读对比
  const hue = 33 + t * 12
  const light = 62 + t * 22
  const sat = 52 - t * 18
  return `hsl(${hue}, ${sat}%, ${light}%)`
}

function renderFire() {
  clearLayer('fire')
  if (!props.layerVisibility.fire) return
  const center = fireGps()
  const gcj = wgs2gcj(center.latitude, center.longitude)
  const lngLat = [gcj.lng, gcj.lat]
  const radius = fireRadiusM()
  const circle = new AMapNS.value.Circle({
    center: lngLat, radius,
    strokeColor: '#ff6a3d', strokeWeight: 2, strokeStyle: 'dashed', strokeOpacity: 0.95,
    fillColor: '#ff5533', fillOpacity: 0.16, bubble: true, zIndex: 52,
  })
  addOverlay('fire', circle)
  const area = Number(props.result?.fire_assessment?.fire_area_m2)
  const marker = new AMapNS.value.Marker({
    position: lngLat, zIndex: 120, anchor: 'bottom-center',
    content: `<div class="tmap-fire"><i></i><span>火点中心${Number.isFinite(area) ? ` · ≈${Math.round(area).toLocaleString()} m²` : ''}</span></div>`,
  })
  marker.on('click', () => emit('select-marker', markerPayload('fire', 'fire', `火点中心 · ${center.longitude.toFixed(6)}°E · ${center.latitude.toFixed(6)}°N`, lngLat)))
  addOverlay('fire', marker, { id: 'fire' })
}

function renderContours() {
  clearLayer('contour')
  if (!props.layerVisibility.contour) return
  const features = Array.isArray(props.contours?.features) ? props.contours.features : []
  if (!features.length) return
  const elevations = features.map((f) => Number(f.properties?.elevation_m)).filter(Number.isFinite)
  const min = Math.min(...elevations)
  const max = Math.max(...elevations)
  let labels = 0
  for (const feature of features) {
    const geometry = feature.geometry
    const lines = geometry?.type === 'LineString' ? [geometry.coordinates] : geometry?.type === 'MultiLineString' ? geometry.coordinates : []
    const elevation = Number(feature.properties?.elevation_m)
    const major = Number.isFinite(elevation) && elevation % 100 === 0
    for (const coordinates of lines) {
      if (coordinates.length < 2) continue
      const path = coordinates.map(([lng, lat]) => {
        const gcj = wgs2gcj(Number(lat), Number(lng))
        return [gcj.lng, gcj.lat]
      })
      const polyline = new AMapNS.value.Polyline({
        path,
        strokeColor: Number.isFinite(elevation) ? contourColor(elevation, min, max) : '#c9b28f',
        strokeWeight: major ? 2 : 1,
        strokeOpacity: major ? 0.8 : 0.4, zIndex: 40, bubble: true,
      })
      addOverlay('contour', polyline)
      if (major && Number.isFinite(elevation) && labels < 40 && coordinates.length > 3) {
        const mid = coordinates[Math.floor(coordinates.length / 2)]
        const gcj = wgs2gcj(Number(mid[1]), Number(mid[0]))
        const text = new AMapNS.value.Marker({
          position: [gcj.lng, gcj.lat], zIndex: 60, anchor: 'center',
          content: `<span class="tmap-contour-label">${elevation}m</span>`,
        })
        addOverlay('contour', text)
        labels += 1
      }
    }
  }
}

function renderWater() {
  clearLayer('water')
  if (!props.layerVisibility.water) return
  const items = props.waterList
  for (const item of items) {
    const gps = waterGps(item)
    if (!gps) continue
    const gcj = wgs2gcj(gps.latitude, gps.longitude)
    const lngLat = [gcj.lng, gcj.lat]
    const marker = new AMapNS.value.Marker({
      position: lngLat, zIndex: item.preferred ? 112 : 104, anchor: 'bottom-center',
      title: `${item.preferred ? '★ ' : ''}${item.name} · ${item.type}`,
      content: elt(`tmap-water ${item.preferred ? 'preferred' : ''}`,
        `<i class="wt-${item.type}"></i><span>${item.preferred ? '★ ' : ''}${item.name}</span><em>${item.type}${item.distance != null ? ` · ${item.distance}m` : ''}</em>`),
    })
    marker.on('click', () => emit('select-marker', markerPayload(item.id, 'water', `${item.preferred ? '首选 · ' : ''}${item.name} · ${item.type}`, lngLat)))
    addOverlay('water', marker, { id: item.id, type: 'water', label: `${item.preferred ? '★ ' : ''}${item.name} · ${item.type}` })
  }
  // 首选水源 → 火点取水路线（虚线 + 距离标注）
  const preferred = preferredWaterItem()
  if (preferred) {
    const from = waterGps(preferred)
    if (from) {
      const a = wgs2gcj(from.latitude, from.longitude)
      const fire = fireGps()
      const b = wgs2gcj(fire.latitude, fire.longitude)
      const path = [[a.lng, a.lat], [b.lng, b.lat]]
      const line = new AMapNS.value.Polyline({
        path, strokeColor: '#3fb8ff', strokeWeight: 2.2, strokeStyle: 'dashed',
        showDir: true, strokeOpacity: 0.9, zIndex: 58,
      })
      addOverlay('water', line)
      const mid = path[0].map((v, i) => (v + path[1][i]) / 2)
      const distance = Math.round(haversineM(from.latitude, from.longitude, fire.latitude, fire.longitude))
      const label = new AMapNS.value.Marker({
        position: mid, zIndex: 62, anchor: 'center',
        content: `<span class="tmap-route-label water">取水路线 · ${distance.toLocaleString()} m</span>`,
      })
      addOverlay('water', label)
    }
  }
}

function renderDrones() {
  clearLayer('drone')
  if (!props.layerVisibility.drone) return
  const drones = props.drones || []
  if (!drones.length) return
  const center = fireGps()
  const origin = props.result?.scene?.fire_origin
  drones.forEach((drone, index) => {
    // 优先用 fleet position（同一相对米制框架）换算真实停靠位；缺 position 时退回装饰环形
    let point = null
    if (drone.position && origin) {
      point = offsetWgs(center.latitude, center.longitude, drone.position.x - origin.x, drone.position.y - origin.y)
    } else {
      const radius = Math.max(520, fireRadiusM() * 3 + 260)
      const angle = (index / Math.max(drones.length, 1)) * Math.PI * 2 - Math.PI / 2
      point = offsetWgs(center.latitude, center.longitude, Math.cos(angle) * radius, Math.sin(angle) * radius)
    }
    const gcj = wgs2gcj(point.latitude, point.longitude)
    const lngLat = [gcj.lng, gcj.lat]
    const selected = props.selectedUavs.includes(drone.id)
    const contentNode = elt(`tmap-drone ${selected ? 'selected' : ''}`, `<b>${drone.id}</b><em class="tmap-badge"></em><i></i>`)
    contentNode.dataset.drone = drone.id
    const marker = new AMapNS.value.Marker({
      position: lngLat, zIndex: 108, anchor: 'center',
      title: `${drone.id} ${drone.label} · SOC ${drone.soc ?? '—'}% · ${drone.status}${selected ? ' · 出动' : ''}`,
      content: contentNode,
    })
    marker.on('click', () => emit('select-marker', markerPayload(drone.id, 'drone', drone.id, lngLat)))
    addOverlay('drone', marker, { id: drone.id, type: 'drone', label: drone.id })
  })
}

function renderRoad() {
  clearLayer('road')
  if (!props.layerVisibility.road) return
  const road = props.environment?.road_context?.nearest_transport || props.environment?.road_context?.nearest_vehicle_access_candidate
  const point = road?.nearest_point
  if (!point) return
  const gcjRoad = wgs2gcj(Number(point.latitude), Number(point.longitude))
  const fire = fireGps()
  const gcjFire = wgs2gcj(fire.latitude, fire.longitude)
  const path = [[gcjRoad.lng, gcjRoad.lat], [gcjFire.lng, gcjFire.lat]]
  const line = new AMapNS.value.Polyline({
    path, strokeColor: '#d9a45b', strokeWeight: 2, strokeStyle: 'dashed', strokeOpacity: 0.85, zIndex: 50,
  })
  addOverlay('road', line)
  const marker = new AMapNS.value.Marker({
    position: [gcjRoad.lng, gcjRoad.lat], zIndex: 102, anchor: 'bottom-center',
    content: `<div class="tmap-road"><span>${road.name || '最近道路'}</span><em>${road.distance_m != null ? `${Math.round(Number(road.distance_m)).toLocaleString()} m` : ''}</em></div>`,
  })
  marker.on('click', () => emit('select-marker', markerPayload('road', 'road', `${road.name || '最近道路'} · ${road.distance_m ?? '—'}m`, [gcjRoad.lng, gcjRoad.lat])))
  addOverlay('road', marker, { id: 'road' })
}

function renderEvacuation() {
  clearLayer('evacuation')
  if (!props.layerVisibility.evacuation) return
  const eva = props.result?.agent?.skill_chain?.evacuation
  if (!eva?.found || !Array.isArray(eva.path) || !eva.path.length) return
  const center = fireGps()
  const path = eva.path.map(([c, r]) => {
    const point = offsetWgs(center.latitude, center.longitude, (Number(c) - 6) * 40, (Number(r) - 6) * 40)
    const gcj = wgs2gcj(point.latitude, point.longitude)
    return [gcj.lng, gcj.lat]
  })
  const line = new AMapNS.value.Polyline({
    path, strokeColor: '#22c58b', strokeWeight: 2.4, strokeStyle: 'dashed',
    showDir: true, strokeOpacity: 0.95, zIndex: 56,
  })
  addOverlay('evacuation', line)
  const exit = path[path.length - 1]
  const exitMarker = new AMapNS.value.Marker({
    position: exit, zIndex: 110, anchor: 'bottom-center',
    content: `<div class="tmap-exit"><span>疏散出口</span><em>约 ${eva.estimated_minutes ?? '—'} 分钟</em></div>`,
  })
  addOverlay('evacuation', exitMarker)
}

function renderAll() {
  if (!map.value || !AMapNS.value) return
  renderFire()
  renderContours()
  renderWater()
  renderDrones()
  renderRoad()
  renderEvacuation()
  syncActiveClasses()
  applyWaterZoom()
}

function applyVisibility() {
  if (!map.value) return
  for (const [key, visible] of Object.entries(props.layerVisibility)) {
    for (const overlay of layerOverlays[key] || []) {
      if (visible) overlay.show?.()
      else overlay.hide?.()
    }
    if (key === 'fire' && visible && !layerOverlays.fire.length) renderFire()
    if (key === 'contour' && visible && !layerOverlays.contour.length) renderContours()
    if (key === 'water' && visible && !layerOverlays.water.length) renderWater()
    if (key === 'drone' && visible && !layerOverlays.drone.length) renderDrones()
    if (key === 'road' && visible && !layerOverlays.road.length) renderRoad()
    if (key === 'evacuation' && visible && !layerOverlays.evacuation.length) renderEvacuation()
  }
  applyWaterZoom()
}

// 缩放联动减负：低倍时水源标签互相压盖，仅保留首选水源，放大后展开全部
function applyWaterZoom() {
  if (!map.value || !props.layerVisibility.water) return
  const zoom = map.value.getZoom()
  for (const overlay of layerOverlays.water) {
    if (!overlay.tmapMeta) continue
    const el = overlay.getContent?.()
    const preferred = el instanceof Node && el.classList.contains('preferred')
    if (zoom < 15 && !preferred) overlay.hide?.()
    else overlay.show?.()
  }
}

function syncActiveClasses() {
  for (const [id, overlay] of markerIndex) {
    const el = overlay?.getContent?.()
    const root = el instanceof Node ? el : null
    if (!root) continue
    root.classList.toggle('tmap-active', props.activeMarkerId === id)
    root.classList.toggle('tmap-hover', props.hoveredDroneId === id || props.hoveredWaterId === id)
  }
}

function setDroneClasses() {
  for (const [id, overlay] of markerIndex) {
    const el = overlay?.getContent?.()
    const root = el instanceof Node ? el : null
    if (root && root.dataset?.drone) root.classList.toggle('selected', props.selectedUavs.includes(id))
  }
}

// ---------- 出动推演动画（FE-17）：rAF 时钟驱动 setPosition，相位与后端 simulate_monitor 状态机对齐 ----------
const MISSION_MS_PER_MIN = 1200
const MISSION_PHASE_LABELS = { flying: '出动中', working: '喷洒作业', returning: '返航中', servicing: '基地补水', charging: '基地充电', orbit: '侦察盘旋', parked: '待命' }
let missionRaf = 0

function missionPhaseAt(phases, tMinutes) {
  let acc = 0
  for (const phase of phases) {
    if (phase.minutes === Infinity) return { kind: phase.kind, progress: 0 }
    if (tMinutes < acc + phase.minutes) return { kind: phase.kind, progress: Math.max(0, Math.min(1, (tMinutes - acc) / phase.minutes)) }
    acc += phase.minutes
  }
  const last = phases[phases.length - 1]
  return { kind: last.kind, progress: 1 }
}

function unitBaseGps(unit) {
  const fire = fireGps()
  return offsetWgs(fire.latitude, fire.longitude, unit.dx, unit.dy)
}

function smoothProgress(p) {
  return p * p * (3 - 2 * p)
}

function missionTick() {
  const mission = props.mission
  if (!mission?.active) { missionRaf = 0; return }
  const fire = fireGps()
  const metersPerLat = 111320
  const metersPerLng = 111320 * Math.cos((fire.latitude * Math.PI) / 180)
  const tNow = (Date.now() - mission.startedAt) / MISSION_MS_PER_MIN
  for (const unit of mission.units) {
    const overlay = markerIndex.get(unit.id)
    if (!overlay) continue
    const t = tNow - (unit.anchor || 0)
    const phase = missionPhaseAt(unit.phases, t)
    const base = unitBaseGps(unit)
    let lat = base.latitude
    let lng = base.longitude
    if (phase.kind === 'flying' || phase.kind === 'returning') {
      const p = smoothProgress(phase.progress)
      const from = phase.kind === 'flying' ? base : { latitude: fire.latitude, longitude: fire.longitude }
      const to = phase.kind === 'flying' ? { latitude: fire.latitude, longitude: fire.longitude } : base
      lat = from.latitude + (to.latitude - from.latitude) * p
      lng = from.longitude + (to.longitude - from.longitude) * p
    } else if (phase.kind === 'working') {
      const seed = [...unit.id].reduce((sum, ch) => sum + ch.charCodeAt(0), 0)
      const angle = (seed % 8) * (Math.PI / 4)
      lat = fire.latitude + (45 * Math.sin(angle)) / metersPerLat
      lng = fire.longitude + (45 * Math.cos(angle)) / metersPerLng
    } else if (phase.kind === 'orbit') {
      const angle = (t / 2.5) * Math.PI * 2 - Math.PI / 2
      lat = fire.latitude + (150 * Math.sin(angle)) / metersPerLat
      lng = fire.longitude + (150 * Math.cos(angle)) / metersPerLng
    }
    const gcj = wgs2gcj(lat, lng)
    overlay.setPosition([gcj.lng, gcj.lat])
    const node = overlay.getContent?.()
    const badge = node instanceof Node ? node.querySelector('.tmap-badge') : null
    if (badge) {
      const label = MISSION_PHASE_LABELS[phase.kind] || ''
      if (badge.textContent !== label) badge.textContent = label
      const cls = `tmap-badge ${phase.kind}`
      if (badge.className !== cls) badge.className = cls
    }
  }
  missionRaf = requestAnimationFrame(missionTick)
}

function restartMissionClock() {
  if (missionRaf) cancelAnimationFrame(missionRaf)
  missionRaf = 0
  if (!props.mission?.active) return
  missionRaf = requestAnimationFrame(missionTick)
}

// ---------- 对外命令：右侧栏联动定位/脉冲 ----------
function focusMarker(id) {
  const overlay = markerIndex.get(id)
  if (!overlay || !map.value) return
  map.value.panTo(overlay.getPosition())
  const meta = overlay.tmapMeta
    if (meta && meta.id === id) {
      const lngLat = overlay.getPosition()
      emit('select-marker', markerPayload(meta.id, meta.type || 'drone', meta.label || overlay.getTitle?.() || meta.id, lngLat))
    }
}
function pulseMarker(id) {
  const overlay = markerIndex.get(id)
  if (!overlay) return
  map.value?.panTo(overlay.getPosition())
  const root = overlay.getContent?.()
  if (root instanceof Node) {
    root.classList.remove('tmap-pulse')
    void root.offsetWidth
    root.classList.add('tmap-pulse')
    clearTimeout(pulseTimer)
    pulseTimer = setTimeout(() => root.classList.remove('tmap-pulse'), 2000)
  }
}
defineExpose({ focusMarker, pulseMarker })

// ---------- 生命周期 ----------
watch(() => [props.result, props.environment, props.drones, props.waterList, props.contours, props.selectedUavs], () => renderAll())
watch(() => props.layerVisibility, () => applyVisibility(), { deep: true })
watch(() => [props.activeMarkerId, props.hoveredDroneId, props.hoveredWaterId], () => syncActiveClasses())
watch(() => props.focusPulse, (id) => { if (id) pulseMarker(id) })
watch(() => props.mission, () => restartMissionClock(), { deep: false })

onMounted(async () => {
  const key = import.meta.env.VITE_AMAP_KEY
  const securityCode = import.meta.env.VITE_AMAP_SECURITY_CODE
  if (!key) {
    emit('fallback', 'missing-key')
    return
  }
  try {
    window._AMapSecurityConfig = securityCode ? { securityJsCode: securityCode } : {}
    const AMap = await AMapLoader.load({ key, version: '2.0', plugins: ['AMap.Scale'] })
    AMapNS.value = AMap
    const center = fireGps()
    const gcj = wgs2gcj(center.latitude, center.longitude)
    const instance = new AMap.Map(containerEl.value, {
      viewMode: '2D', pitch: 0, zoom: 14, center: [gcj.lng, gcj.lat],
      mapStyle: 'amap://styles/dark', zooms: [10, 19],
    })
    map.value = instance
    instance.add(new AMap.TileLayer.Satellite({ zIndex: 10 }))
    instance.add(new AMap.TileLayer.RoadNet({ zIndex: 12, opacity: 0.85 }))
    instance.addControl(new AMap.Scale({ position: 'RB' }))
    instance.on('mousemove', (event) => {
      const wgs = gcj2wgs(event.lnglat.getLat(), event.lnglat.getLng())
      emit('coords', { latitude: wgs.lat, longitude: wgs.lng })
    })
    instance.on('zoomend', applyWaterZoom)
    renderAll()
    applyWaterZoom()
    emit('ready')
  } catch (error) {
    console.warn('[TacticalMap] 高德地图加载失败，回退示意图', error)
    emit('fallback', String(error?.message || error))
  }
})

onBeforeUnmount(() => {
  clearTimeout(pulseTimer)
  if (missionRaf) cancelAnimationFrame(missionRaf)
  clearAll()
  if (map.value) {
    map.value.destroy()
    map.value = null
  }
})
</script>

<template>
  <div ref="containerEl" class="tactical-amap" role="application" aria-label="紫金山真实卫星态势图（高德）"></div>
</template>
