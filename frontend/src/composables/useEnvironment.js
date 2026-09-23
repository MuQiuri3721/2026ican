import { computed, ref } from 'vue'
import { waterTypeLabel } from '../utils/labels'

export function useEnvironment({ sceneId, addLog, onCoordinateApplied }) {
  const environment = ref(null)
  const environmentLoading = ref(false)
  const environmentMode = ref('real')
  const environmentCoordinates = ref({ latitude: 32.0725, longitude: 118.8415 })
  const coordinateDraft = ref({ ...environmentCoordinates.value })
  const coordinateError = ref('')
  const environmentRequestToken = ref(0)

  const environmentAgeText = computed(() => {
    const ts = environment.value?.collected_at
    if (!ts) return ''
    const seconds = Math.round((Date.now() - new Date(ts).getTime()) / 1000)
    if (!Number.isFinite(seconds) || seconds < 0) return ''
    if (seconds < 60) return `${seconds} 秒前`
    if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`
    return `${Math.floor(seconds / 3600)} 小时前`
  })
  const environmentStatus = computed(() => environment.value?.status || '未加载')
  // 页面设计（2026-09）：主界面不出现内部服务名，来源统一换算为中文口径
  const ENV_SOURCE_LABELS = { environment_service: '环境服务实测', open_meteo: '气象服务实测', amap: '高德实测', osm: '开放街图', overpass: '开放街图', environment_cache: '环境缓存', demo: '演示数据' }
  const environmentSource = computed(() => {
    const raw = environment.value?.source
    if (!raw) return '—'
    return ENV_SOURCE_LABELS[raw] || (raw.includes('cache') ? '环境缓存' : raw.includes('demo') ? '演示数据' : '实测数据')
  })
  const environmentStale = computed(() => Boolean(environment.value?.stale))
  const environmentFallback = computed(() => environment.value?.fallback?.message || '')
  const environmentLocation = computed(() => environment.value?.location || environmentCoordinates.value)

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
    onCoordinateApplied?.()
    addLog(`火点坐标已更新 · ${latitude.toFixed(7)}, ${longitude.toFixed(7)}`)
  }

  async function loadEnvironment() {
    const requestToken = ++environmentRequestToken.value
    environmentLoading.value = true
    try {
      const { latitude, longitude } = environmentCoordinates.value
      const query = new URLSearchParams({ scene_id: sceneId, latitude: String(latitude), longitude: String(longitude), environment_mode: environmentMode.value, water_radius_m: '5000', road_radius_m: '5000' })
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

  return {
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
  }
}
