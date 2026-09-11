<script setup>
// 三维地形视图（FE-29，移植自 firepatrol-agents Terrain3D，适配 2026ican 数据契约）：
// SRTM 高程网格位移地形（顶点配色+山体阴影烘焙）+ 火点火焰/烟柱/光晕 + 六角色机群四旋翼
// （与 TacticalMap 同一套 mission 相位时钟）+ 基地/水源标站 + 疏散路线。纯展示，不回写任何数据。
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'

const props = defineProps({
  grid: { type: Object, default: null },          // /api/terrain/grid 结果
  fireGps: { type: Object, default: null },       // { latitude, longitude }
  fireRadiusM: { type: Number, default: 120 },
  fireActive: { type: Boolean, default: false },
  drones: { type: Array, default: () => [] },     // [{id, subgroup, soc, position, speed_mps}]
  mission: { type: Object, default: null },       // 与 TacticalMap 同源的出动推演对象
  fireOrigin: { type: Object, default: null },    // 相对米制原点 {x, y}
  stations: { type: Array, default: () => [] },   // [{name, gps:{latitude, longitude}, color}]
  evacPath: { type: Array, default: () => [] },   // [{latitude, longitude}]
  peopleStatus: { type: String, default: 'unknown' },
})

const EX = 2.2
const MISSION_MS_PER_MIN = 1200
const PHASE_LABELS = { flying: '出动中', working: '喷洒作业', returning: '返航中', servicing: '基地补水', charging: '基地充电', orbit: '侦察盘旋', parked: '待命' }
const SUBGROUP_COLOR = { reconnaissance: 0x4f8dff, suppression: 0xff7a45, support: 0x2fbd8b }

const mountRef = ref(null)
const ready = ref(false)
const core = shallowRef(null)
const droneIndex = shallowRef(new Map())   // id -> {group, rotors, spray, badge, cur, anchor}
const raf = shallowRef(0)
const fallbackTimer = shallowRef(0)

function metersPerLat() { return 111320 }
function metersPerLng(lat) { return 111320 * Math.cos((lat * Math.PI) / 180) }

// 经纬度 → 世界坐标（以网格西南角为原点，米）
function toWorld(lat, lng) {
  const grid = props.grid
  if (!grid) return null
  const x = (lng - grid.lon0) * metersPerLng(grid.lat0)
  const z = (grid.lat0 - lat) * metersPerLat()
  return { x: x - grid.scene_w / 2, z: z - grid.scene_h / 2 }
}

function elevAt(lat, lng) {
  const grid = props.grid
  if (!grid) return grid?.min_elev ?? 0
  const gx = Math.max(0, Math.min(grid.nx - 1, Math.round((lng - grid.lon0) / (grid.lon1 - grid.lon0) * (grid.nx - 1))))
  const gy = Math.max(0, Math.min(grid.ny - 1, Math.round((grid.lat0 - lat) / (grid.lat0 - grid.lat1) * (grid.ny - 1))))
  return grid.elevations[gy]?.[gx] ?? grid.min_elev
}

function smoothProgress(p) { return p * p * (3 - 2 * p) }

// 递归释放几何体/材质/纹理（rebuild 频繁重建地形与精灵，不释放会持续泄漏 GPU 内存）
function disposeObject(root) {
  root.traverse((obj) => {
    if (obj.geometry) obj.geometry.dispose()
    const materials = Array.isArray(obj.material) ? obj.material : (obj.material ? [obj.material] : [])
    for (const mat of materials) {
      if (mat.map) mat.map.dispose()
      mat.dispose()
    }
  })
}

function phaseAt(phases, tMinutes) {
  let acc = 0
  for (const phase of phases) {
    if (phase.minutes === Infinity) return { kind: phase.kind, progress: 0 }
    if (tMinutes < acc + phase.minutes) return { kind: phase.kind, progress: Math.max(0, Math.min(1, (tMinutes - acc) / phase.minutes)) }
    acc += phase.minutes
  }
  return { kind: phases[phases.length - 1].kind, progress: 1 }
}

// ---------- 场景构建 ----------
function buildTerrain(three, grid, world) {
  const geometry = new THREE.PlaneGeometry(grid.scene_w, grid.scene_h, grid.nx - 1, grid.ny - 1)
  geometry.rotateX(-Math.PI / 2)
  const pos = geometry.attributes.position
  const colors = []
  const colValley = new THREE.Color('#467a63')
  const colMid = new THREE.Color('#64886a')
  const colHigh = new THREE.Color('#8a8060')
  const colPeak = new THREE.Color('#b0a68c')
  const sun = new THREE.Vector3(-0.55, 0.75, 0.35).normalize()
  const span = grid.max_elev - grid.min_elev || 1
  const height = (r, c) => grid.elevations[Math.max(0, Math.min(grid.ny - 1, r))]?.[Math.max(0, Math.min(grid.nx - 1, c))] ?? grid.min_elev
  for (let i = 0; i < pos.count; i++) {
    const gx = i % grid.nx
    const gy = Math.floor(i / grid.nx)
    pos.setY(i, (height(gy, gx) - grid.min_elev) * EX)
  }
  for (let i = 0; i < pos.count; i++) {
    const gx = i % grid.nx
    const gy = Math.floor(i / grid.nx)
    const h = height(gy, gx)
    const t = (h - grid.min_elev) / span
    const c = t < 0.45 ? colValley.clone().lerp(colMid, t / 0.45) : t < 0.8 ? colMid.clone().lerp(colHigh, (t - 0.45) / 0.35) : colHigh.clone().lerp(colPeak, (t - 0.8) / 0.2)
    const dhx = height(gy, gx + 1) - height(gy, gx - 1)
    const dhy = height(gy + 1, gx) - height(gy - 1, gx)
    const normal = new THREE.Vector3(-dhx * EX, 40, -dhy * EX).normalize()
    c.multiplyScalar(0.85 + 0.5 * Math.max(0, normal.dot(sun)))
    colors.push(c.r, c.g, c.b)
  }
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3))
  geometry.computeVertexNormals()
  world.add(new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.96, metalness: 0.02 })))
}

function buildSky(three, scene) {
  const canvas = document.createElement('canvas')
  canvas.width = 8
  canvas.height = 512
  const ctx = canvas.getContext('2d')
  const grad = ctx.createLinearGradient(0, 0, 0, 512)
  grad.addColorStop(0, '#0e2018')
  grad.addColorStop(0.42, '#24382c')
  grad.addColorStop(0.66, '#3a3020')
  grad.addColorStop(0.8, '#221c12')
  grad.addColorStop(1, '#0c0e0a')
  ctx.fillStyle = grad
  ctx.fillRect(0, 0, 8, 512)
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  const dome = new THREE.Mesh(new THREE.SphereGeometry(4200, 32, 20), new THREE.MeshBasicMaterial({ map: tex, side: THREE.BackSide, fog: false }))
  scene.add(dome)
  return dome
}

function buildStation(three, world, station, groundY) {
  const color = new THREE.Color(station.color)
  const K = station.scaleK ?? 1
  const pillar = new THREE.Mesh(new THREE.CylinderGeometry(10 * K, 14 * K, 30 * K, 8), new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.45, roughness: 0.5 }))
  pillar.position.y = groundY + 15 * K
  const ring = new THREE.Mesh(new THREE.RingGeometry(20 * K, 28 * K, 36), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.5, side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false }))
  ring.rotation.x = -Math.PI / 2
  ring.position.y = groundY + 2
  const tag = textSprite(station.name, '#' + color.getHexString(), 0.8 * K)
  tag.position.y = groundY + 52 * K
  const group = new THREE.Group()
  group.add(pillar, ring, tag)
  group.position.copy(station.world)
  world.add(group)
}

function textSprite(text, color, scale = 1) {
  const canvas = document.createElement('canvas')
  canvas.width = 256
  canvas.height = 96
  const ctx = canvas.getContext('2d')
  ctx.fillStyle = 'rgba(8,16,12,0.72)'
  ctx.beginPath()
  ctx.roundRect(6, 22, 244, 52, 12)
  ctx.fill()
  ctx.strokeStyle = color
  ctx.lineWidth = 3
  ctx.stroke()
  ctx.fillStyle = color
  ctx.font = 'bold 38px Bahnschrift, "Microsoft YaHei", sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(text, 128, 50)
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }))
  sprite.scale.set(56 * scale, 21 * scale, 1)
  return sprite
}

function radialTexture(inner, outer, size = 128) {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const ctx = canvas.getContext('2d')
  const g = ctx.createRadialGradient(size / 2, size / 2, 2, size / 2, size / 2, size / 2)
  g.addColorStop(0, inner)
  g.addColorStop(0.35, inner)
  g.addColorStop(1, outer)
  ctx.fillStyle = g
  ctx.fillRect(0, 0, size, size)
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

// ---------- 四旋翼（与 firepatrol 同款造型：机身+旋翼+航行灯+子群挂载） ----------
function buildDrone(colorHex, subgroup) {
  const group = new THREE.Group()
  const color = new THREE.Color(colorHex)
  const matAir = new THREE.MeshStandardMaterial({ color: '#3a4450', roughness: 0.42, metalness: 0.45 })
  const matDark = new THREE.MeshStandardMaterial({ color: '#171c22', roughness: 0.55, metalness: 0.3 })
  const matAccent = new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.5, roughness: 0.35 })
  group.add(new THREE.Mesh(new THREE.BoxGeometry(13, 5, 17), matAir))
  const canopy = new THREE.Mesh(new THREE.SphereGeometry(5.2, 18, 12), new THREE.MeshStandardMaterial({ color: '#0d141c', emissive: color, emissiveIntensity: 0.3, roughness: 0.15, metalness: 0.65 }))
  canopy.scale.set(1.05, 0.48, 1.32)
  canopy.position.y = 2.6
  group.add(canopy)
  const rotors = []
  const matDisc = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.15, side: THREE.DoubleSide, depthWrite: false })
  for (const [dx, dz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
    const arm = new THREE.Mesh(new THREE.BoxGeometry(1.6, 1.1, 12.5), matAir)
    arm.position.set(dx * 4.6, 0.9, dz * 4.6)
    arm.rotation.y = Math.atan2(dx, dz)
    group.add(arm)
    const prop = new THREE.Group()
    prop.position.set(dx * 8.8, 3.7, dz * 8.8)
    prop.add(new THREE.Mesh(new THREE.CylinderGeometry(0.7, 0.7, 1, 8), matAccent))
    prop.add(new THREE.Mesh(new THREE.BoxGeometry(12.4, 0.22, 1.15), matDark))
    prop.add(new THREE.Mesh(new THREE.CylinderGeometry(6.3, 6.3, 0.05, 24), matDisc))
    group.add(prop)
    rotors.push(prop)
  }
  const body = new THREE.Mesh(new THREE.SphereGeometry(3.2, 12, 10), matAccent)
  body.position.y = 0.5
  group.add(body)
  if (subgroup === 'suppression') {
    const tank = new THREE.Mesh(new THREE.BoxGeometry(8.6, 3.8, 11), new THREE.MeshStandardMaterial({ color: '#d92b2b', roughness: 0.4 }))
    tank.position.set(0, -4.6, -0.5)
    group.add(tank)
  } else if (subgroup === 'support') {
    const crate = new THREE.Mesh(new THREE.BoxGeometry(8.6, 3.6, 11), new THREE.MeshStandardMaterial({ color: '#4d5d3a', roughness: 0.7 }))
    crate.position.set(0, -4.5, -0.5)
    group.add(crate)
  } else {
    const gimbal = new THREE.Mesh(new THREE.SphereGeometry(2.4, 12, 10), matDark)
    gimbal.position.set(0, -4.2, 5)
    group.add(gimbal)
  }
  return { group, rotors }
}

// ---------- 火点（火焰精灵+烟柱+火光） ----------
function buildFire(three, dynamic, world, K) {
  if (!props.fireActive || !props.fireGps) return
  const w = toWorld(props.fireGps.latitude, props.fireGps.longitude)
  if (!w) return
  const gy = elevAt(props.fireGps.latitude, props.fireGps.longitude) * EX
  const fireTex = radialTexture('rgba(255,220,150,1)', 'rgba(255,80,20,0)')
  const smokeTex = radialTexture('rgba(125,125,125,0.5)', 'rgba(80,80,80,0)')
  for (let k = 0; k < 5; k++) {
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: fireTex, color: k % 2 ? '#ffb35c' : '#ff7a2e', transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, opacity: 0.85 }))
    sprite.position.set(w.x + (k - 2) * 22 * K, gy + 26 * K + (k % 3) * 20 * K, w.z + ((k * 7) % 3 - 1) * 22 * K)
    sprite.userData = { fireSprite: true, seed: k * 0.37, baseScale: (46 + k * 8) * K, baseY: sprite.position.y }
    dynamic.add(sprite)
  }
  const smoke = new THREE.Sprite(new THREE.SpriteMaterial({ map: smokeTex, transparent: true, opacity: 0.3, depthWrite: false }))
  smoke.position.set(w.x, gy + 90 * K, w.z)
  smoke.scale.set(80 * K, 80 * K, 1)
  smoke.userData = { smoke: true, seed: 0.2, x: w.x, y0: gy + 90 * K, z: w.z }
  dynamic.add(smoke)
  const light = new THREE.PointLight('#ff7a2e', 4, props.fireRadiusM * 6, 1.6)
  light.position.set(w.x, gy + 50 * K, w.z)
  light.userData = { fireLight: true, seed: 1 }
  dynamic.add(light)
  const scorch = new THREE.Mesh(new THREE.CircleGeometry(Math.max(120, props.fireRadiusM * 2.2), 36),
    new THREE.MeshBasicMaterial({ color: '#8a2410', transparent: true, opacity: 0.55 }))
  scorch.rotation.x = -Math.PI / 2
  scorch.position.set(w.x, gy + 1.5, w.z)
  dynamic.add(scorch)
}

// ---------- 机群 ----------
function droneWorld(drone) {
  const fire = props.fireGps
  const origin = props.fireOrigin
  if (!fire) return null
  let lat = fire.latitude
  let lng = fire.longitude
  if (drone.position && origin) {
    lat += (drone.position.y - origin.y) / metersPerLat()
    lng += (drone.position.x - origin.x) / metersPerLng(fire.latitude)
  }
  return { latitude: lat, longitude: lng }
}

function syncDrones(three, dynamic, grid) {
  const index = droneIndex.value
  const seen = new Set()
  for (const drone of props.drones) {
    seen.add(drone.id)
    const w = droneWorld(drone)
    if (!w) continue
    const groundY = elevAt(w.latitude, w.longitude) * EX
    const alt = groundY + 60 * EX
    let entry = index.get(drone.id)
    if (!entry) {
      const colorHex = '#' + new THREE.Color(SUBGROUP_COLOR[drone.subgroup] ?? 0x4f8dff).getHexString()
      const built = buildDrone(colorHex, drone.subgroup)
      built.group.scale.setScalar(grid.scene_w / 900)
      const badge = textSprite(`${drone.id} · ${drone.soc ?? '—'}%`, colorHex, 0.8)
      badge.position.y = 34
      built.group.add(badge)
      dynamic.add(built.group)
      entry = { ...built, badge, cur: null }
      index.set(drone.id, entry)
    }
    entry.target = { x: w.x, y: alt, z: w.z, lat: w.latitude, lng: w.longitude, groundY }
    // BE-17：无任务（待命）时机群散布悬停在驻地上空——此前 syncDrones 只登记不摆放，
    // 12 架全部叠在世界原点（埋进地形），缩放也小到镜头下不可见。
    if (!props.mission?.active) {
      const idx = Math.max(0, props.drones.indexOf(drone))
      const angle = idx * 2.399
      const radius = 300 + (idx % 6) * 120
      const lat = w.latitude + Math.sin(angle) * radius / 111320
      const lng = w.longitude + Math.cos(angle) * radius / (111320 * Math.cos(w.latitude * Math.PI / 180))
      const gw = toWorld(lat, lng)
      if (gw) {
        entry.target.x = gw.x
        entry.target.z = gw.z
        entry.target.y = elevAt(lat, lng) * EX + 46 * EX
        entry.target.lat = lat
        entry.target.lng = lng
      }
      if (!entry.cur) entry.cur = { ...entry.target }
      entry.cur.x += (entry.target.x - entry.cur.x) * 0.08
      entry.cur.y += (entry.target.y - entry.cur.y) * 0.08
      entry.cur.z += (entry.target.z - entry.cur.z) * 0.08
      entry.group.position.set(entry.cur.x, entry.cur.y, entry.cur.z)
    }
  }
  for (const [id, entry] of index) {
    if (!seen.has(id)) {
      disposeObject(entry.group)
      dynamic.remove(entry.group)
      index.delete(id)
    }
  }
}

function missionTick(three, ts) {
  const mission = props.mission
  const index = droneIndex.value
  if (!mission?.active) {
    for (const entry of index.values()) entry.badge.material.opacity = 1
    return
  }
  const fire = props.fireGps
  if (!fire) return
  const now = (Date.now() - mission.startedAt) / MISSION_MS_PER_MIN
  const mpl = metersPerLat()
  const mpg = metersPerLng(fire.latitude)
  for (const unit of mission.units) {
    const entry = index.get(unit.id)
    if (!entry || !entry.target) continue
    const t = now - (unit.anchor || 0)
    const phase = phaseAt(unit.phases, t)
    const base = { latitude: fire.latitude + unit.dy / mpl, longitude: fire.longitude + unit.dx / mpg }
    let lat = base.latitude
    let lng = base.longitude
    if (phase.kind === 'flying' || phase.kind === 'returning') {
      const p = smoothProgress(phase.progress)
      const from = phase.kind === 'flying' ? base : fire
      const to = phase.kind === 'flying' ? fire : base
      lat = from.latitude + (to.latitude - from.latitude) * p
      lng = from.longitude + (to.longitude - from.longitude) * p
    } else if (phase.kind === 'working') {
      const seed = [...unit.id].reduce((sum, ch) => sum + ch.charCodeAt(0), 0)
      const angle = (seed % 8) * (Math.PI / 4)
      lat = fire.latitude + (120 * Math.sin(angle)) / mpl
      lng = fire.longitude + (120 * Math.cos(angle)) / mpg
    } else if (phase.kind === 'orbit') {
      const angle = (t / 2.5) * Math.PI * 2 - Math.PI / 2
      lat = fire.latitude + (150 * Math.sin(angle)) / mpl
      lng = fire.longitude + (150 * Math.cos(angle)) / mpg
    }
    const w = toWorld(lat, lng)
    if (!w) continue
    const groundY = elevAt(lat, lng) * EX
    const target = { x: w.x, y: groundY + 60 * EX, z: w.z }
    if (!entry.cur) entry.cur = { ...target }
    entry.cur.x += (target.x - entry.cur.x) * 0.12
    entry.cur.y += (target.y - entry.cur.y) * 0.12
    entry.cur.z += (target.z - entry.cur.z) * 0.12
    entry.group.position.set(entry.cur.x, entry.cur.y + Math.sin(ts / 850 + unit.id.charCodeAt(0)) * 2.2, entry.cur.z)
    entry.group.rotation.y = Math.atan2(fire.longitude - base.longitude, fire.latitude - base.latitude)
    const label = PHASE_LABELS[phase.kind] || ''
    if (entry.badge.userData.label !== label) {
      entry.badge.userData.label = label
      entry.badge.material.map.dispose()
      entry.badge.material.map = textSprite(`${unit.id} · ${label}`, '#9cc2ff', 0.55).material.map
      entry.badge.material.needsUpdate = true
    }
    for (const rotor of entry.rotors) rotor.rotation.y += 0.85
  }
}

function animate(three, ts) {
  try {
    animateInner(three, ts)
  } catch (error) {
    window.__t3d_error = String(error && error.stack || error)
  }
}

function animateInner(three, ts) {
  const { controls, dynamic, camera, renderer, scene } = three
  for (const child of dynamic.children) {
    const meta = child.userData ?? {}
    if (meta.fireSprite) {
      const flicker = 0.72 + 0.28 * Math.sin(ts / 130 + meta.seed * 7)
      child.scale.set(meta.baseScale * flicker, meta.baseScale * 1.25 * flicker, 1)
      child.position.y = meta.baseY + Math.sin(ts / 460 + meta.seed * 3) * 9
    }
    if (meta.smoke) {
      const cycle = (ts / 5200 + meta.seed) % 1
      child.position.set(meta.x + Math.sin(cycle * 6.28) * 26, meta.y0 + cycle * 200, meta.z + Math.cos(cycle * 5) * 20)
      const s = 80 + cycle * 180
      child.scale.set(s, s, 1)
      child.material.opacity = 0.34 * (1 - cycle)
    }
    if (meta.fireLight) child.intensity = 4 + 1.6 * Math.sin(ts / 90 + meta.seed)
  }
  missionTick(three, ts)
  controls.update()
  renderer.render(scene, camera)
  raf.value = requestAnimationFrame((next) => animate(three, next))
}

// ---------- 重建静态层（网格/标站/火点/疏散线） ----------
function rebuild() {
  try {
    rebuildInner()
  } catch (error) {
    window.__t3d_error = String(error && error.stack || error)
  }
}

function rebuildInner() {
  const entry = core.value
  const grid = props.grid
  if (!entry || !grid) return
  const { world, dynamic } = entry
  disposeObject(world)
  disposeObject(dynamic)
  world.clear()
  dynamic.clear()
  grid.scene_w = (grid.lon1 - grid.lon0) * metersPerLng(grid.lat0)
  grid.scene_h = grid.lat0 - grid.lat1
  const K = grid.scene_w / 2000  // 场景比例因子（firepatrol 基准 2000m）
  const three = { THREE }
  entry.scene.fog.near = grid.scene_w * 1.1
  entry.scene.fog.far = grid.scene_w * 2.6
  entry.sky.scale.setScalar(Math.max(1, grid.scene_w / 6500))
  entry.camera.far = grid.scene_w * 4
  entry.camera.updateProjectionMatrix()
  // 取景对准火点（无火时看场景中心）：仅首次放置，之后尊重用户拖拽的视角
  if (!entry.cameraPlaced) {
    entry.cameraPlaced = true
    const fireW = props.fireGps ? toWorld(props.fireGps.latitude, props.fireGps.longitude) : null
    const focus = fireW || { x: 0, z: 0 }
    entry.controls.target.set(focus.x, 260, focus.z)
    entry.camera.position.set(focus.x - grid.scene_w * 0.42, grid.scene_w * 0.62, focus.z + grid.scene_w * 0.52)
  }
  buildTerrain(three, grid, world)
  for (const station of props.stations) {
    const w = toWorld(station.gps.latitude, station.gps.longitude)
    if (w) buildStation(three, world, { ...station, scaleK: K, world: new THREE.Vector3(w.x, 0, w.z) }, elevAt(station.gps.latitude, station.gps.longitude) * EX)
  }
  buildFire(three, dynamic, world, K)
  if (props.evacPath.length > 1) {
    const pts = props.evacPath
      .map((pt) => {
        const w = toWorld(pt.latitude, pt.longitude)
        return w ? new THREE.Vector3(w.x, elevAt(pt.latitude, pt.longitude) * EX + 8, w.z) : null
      })
      .filter(Boolean)
    if (pts.length > 1) {
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineDashedMaterial({ color: '#5eead4', dashSize: 26, gapSize: 14 }))
      line.computeLineDistances()
      world.add(line)
    }
  }
  droneIndex.value = new Map()
  syncDrones(three, dynamic, grid)
}

onMounted(() => {
  const mount = mountRef.value
  if (!mount) return
  const renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setClearColor('#0a1410')
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.6
  mount.appendChild(renderer.domElement)
  const camera = new THREE.PerspectiveCamera(46, 1, 1, 9000)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.08
  controls.autoRotate = true
  controls.autoRotateSpeed = 0.4
  controls.target.set(0, 220, 0)
  controls.maxDistance = 4600
  controls.minDistance = 200
  const scene = new THREE.Scene()
  scene.fog = new THREE.Fog('#1c2822', 3000, 12000)
  const sky = buildSky(THREE, scene)
  scene.add(new THREE.HemisphereLight('#b8d0c0', '#2a3428', 1.35))
  const sun = new THREE.DirectionalLight('#ffd9a3', 1.8)
  sun.position.set(-900, 1200, 600)
  scene.add(sun)
  const fill = new THREE.DirectionalLight('#5f8fca', 0.55)
  fill.position.set(800, 500, -900)
  scene.add(fill)
  const world = new THREE.Group()
  const dynamic = new THREE.Group()
  scene.add(world, dynamic)
  core.value = { renderer, camera, controls, scene, world, dynamic, sky }
  const resize = () => {
    const rect = mount.getBoundingClientRect()
    if (rect.width < 8 || rect.height < 8) return
    renderer.setSize(rect.width, rect.height, false)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    camera.aspect = rect.width / rect.height
    camera.updateProjectionMatrix()
  }
  const observer = new ResizeObserver(resize)
  observer.observe(mount)
  resize()
  ready.value = true
  rebuild()
  raf.value = requestAnimationFrame((ts) => animate(core.value, ts))
})

onBeforeUnmount(() => {
  if (raf.value) cancelAnimationFrame(raf.value)
  if (fallbackTimer.value) clearInterval(fallbackTimer.value)
  const entry = core.value
  if (entry) {
    entry.controls.dispose()
    entry.renderer.dispose()
    mountRef.value?.removeChild(entry.renderer.domElement)
    core.value = null
  }
})

watch(() => [props.grid, props.stations, props.fireGps, props.fireActive, props.evacPath], rebuild, { deep: false })
watch(() => props.drones, () => {
  const entry = core.value
  const grid = props.grid
  if (!entry || !grid) return
  syncDrones(THREE, entry.dynamic, grid)
})
// TacticalMap 挂载时须手动重启推演时钟的同类坑：mission 变化后重启兜底计时器
watch(() => props.mission, () => { if (core.value && !raf.value) raf.value = requestAnimationFrame((ts) => animate(core.value, ts)) }, { deep: false })

// 后台标签 rAF 节流兜底
let throttleTimer = 0
let lastTick = 0
onMounted(() => {
  throttleTimer = window.setInterval(() => {
    if (document.hidden && core.value && Date.now() - lastTick > 220) {
      lastTick = Date.now()
      animate(core.value, lastTick)
    }
  }, 160)
})
onBeforeUnmount(() => {
  if (throttleTimer) { clearInterval(throttleTimer); throttleTimer = 0 }
})
</script>

<template>
  <div class="terrain3d-wrap">
    <div ref="mountRef" class="terrain3d" role="application" aria-label="紫金山三维地形（拖拽旋转 / 滚轮缩放）"></div>
    <span v-if="grid" class="terrain3d-tag">紫金山实测高程 · 拖拽旋转 / 滚轮缩放 / 自动巡航</span>
  </div>
</template>

<style scoped>
.terrain3d-wrap { position: absolute; inset: 0; }
.terrain3d { position: absolute; inset: 0; }
.terrain3d-tag { position: absolute; left: 12px; bottom: 10px; font: 500 11px/1.2 var(--font-data, monospace); color: #9fb8a8; background: #101820cc; padding: 5px 10px; border-radius: 999px; pointer-events: none; }
</style>
