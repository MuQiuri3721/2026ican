// 出动推演时钟（B-8 二波组合式提取，FE-17 逻辑原样迁移）：
// 批准即动画、自动轮次推进、后端权威校准。相位时间线与后端 simulate_monitor
// 状态机对齐（flying→working→returning→servicing→charging）。
// onAutoTick：自动推演的每轮触发回调（App 注入 () => runMonitor(true)，解除循环依赖）。
import { ref } from 'vue'
import { MISSION_MS_PER_MIN, MISSION_PHASE_LABELS, MISSION_ROUND_MS } from '../constants'

export function useMissionClock({ plan, drones, analysisResult, environmentCoordinates, addLog, onAutoTick }) {
  const mission = ref(null)
  const missionNow = ref(0)
  // FE-60：推演速度倍率——改变的是仿真分钟与真实秒的换算，已流逝的仿真分钟在切换时重基保持连续
  const simSpeed = ref(1)
  function setSimSpeed(speed) {
    const current = mission.value
    if (!current?.active) { simSpeed.value = speed; return }
    const elapsedMin = (Date.now() - current.startedAt) / (current.msPerMin || MISSION_MS_PER_MIN)
    current.msPerMin = MISSION_MS_PER_MIN / speed
    current.startedAt = Date.now() - elapsedMin * current.msPerMin
    simSpeed.value = speed
    startAutoSim()
  }
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
    return { active: true, startedAt: Date.now(), units, msPerMin: MISSION_MS_PER_MIN / (simSpeed.value || 1) }
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
      if (mission.value?.active) missionNow.value = (Date.now() - mission.value.startedAt) / (mission.value.msPerMin || MISSION_MS_PER_MIN)
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
    missionTimer = window.setInterval(() => { onAutoTick() }, MISSION_ROUND_MS / (simSpeed.value || 1))
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

  return {
    mission, missionNow, simSpeed, setSimSpeed,
    startMission, stopMission, startAutoSim, stopAutoSim, reconcileMission,
    missionPhaseText, fireGpsValue,
  }
}
