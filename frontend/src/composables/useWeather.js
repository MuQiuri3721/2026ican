// 高德实时天气（FE-80，设计稿顶栏天气 chip）：复用 JS API Key——Geocoder 逆地理把
// 当前环境坐标换 adcode，Weather 插件取实况。天气是背景信息，不参与 FLP 计算（冻结口径
// 不变）；坐标在境外/海域、Key 缺失或 AMap 不可用时 weather=null，chip 诚实隐藏不摆假数。
// 同一 adcode 结果缓存 30 分钟（实况约每小时更新），坐标变化才重新逆地理。
import { ref } from 'vue'
import { loadAmap } from '../amap'

const WEATHER_TTL_MS = 30 * 60 * 1000
const weather = ref(null)
let adcodeCache = null // { key: 'lng,lat(4位)', value: addressComponent }
let lastDoneAt = 0
let inflight = null
let seq = 0

export function useWeather() {
  return { weather, refreshWeather }
}

export function refreshWeather(coordinates) {
  if (!coordinates || inflight) return inflight || Promise.resolve()
  const now = Date.now()
  const key = `${Number(coordinates.longitude).toFixed(4)},${Number(coordinates.latitude).toFixed(4)}`
  const sameSpot = adcodeCache && adcodeCache.key === key
  if (weather.value && sameSpot && now - lastDoneAt < WEATHER_TTL_MS) return Promise.resolve()
  const ticket = ++seq
  inflight = (async () => {
    try {
      const AMap = await loadAmap(['AMap.Geocoder', 'AMap.Weather']).catch(() => null)
      if (!AMap || ticket !== seq) return
      let address = sameSpot ? adcodeCache.value : null
      if (!address) {
        // 坐标→adcode 用逆地理 getAddress（getLocation 是正向编码，地址→坐标）
        address = await new Promise((resolve) => {
          new AMap.Geocoder().getAddress([Number(coordinates.longitude), Number(coordinates.latitude)], (status, result) => {
            const component = status === 'complete' ? result?.regeocode?.addressComponent : null
            resolve(component && component.adcode ? component : null)
          })
        })
        if (ticket !== seq) return
        if (!address) { weather.value = null; return } // 境外/逆地理失败：不展示
        adcodeCache = { key, value: address }
      }
      const live = await new Promise((resolve) => {
        new AMap.Weather().getLive(address.adcode, (error, data) => resolve(error || !data ? null : data))
      })
      if (ticket !== seq) return
      lastDoneAt = Date.now()
      if (!live || live.temperature == null || live.temperature === '') { weather.value = null; return }
      weather.value = {
        temperature: live.temperature,
        text: live.weather || '—',
        humidity: live.humidity,
        windDirection: live.windDirection,
        windPower: live.windPower,
        district: address.district || address.city || '',
        reportTime: live.reportTime || '',
      }
    } finally {
      if (ticket === seq) inflight = null
    }
  })()
  return inflight
}
