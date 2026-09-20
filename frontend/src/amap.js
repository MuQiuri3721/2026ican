// AMap JS API 共享加载器：全应用只 load 一次（TacticalMap 底图 / useWeather 天气共用），
// 后续调用复用同一命名空间，缺的插件用 AMap.plugin 运行期补插。
// Key 缺失时 reject，由调用方各自诚实降级（底图回退等高线示意图 / 天气 chip 隐藏）。
import AMapLoader from '@amap/amap-jsapi-loader'

let promise = null

export function loadAmap(extraPlugins = []) {
  if (!promise) {
    const key = import.meta.env.VITE_AMAP_KEY
    if (!key) return Promise.reject(new Error('VITE_AMAP_KEY 未配置'))
    const securityCode = import.meta.env.VITE_AMAP_SECURITY_CODE
    window._AMapSecurityConfig = securityCode ? { securityJsCode: securityCode } : {}
    promise = AMapLoader.load({ key, version: '2.0', plugins: [] })
  }
  if (!extraPlugins.length) return promise
  return promise.then(
    (AMap) => new Promise((resolve, reject) => {
      try { AMap.plugin(extraPlugins, () => resolve(AMap)) } catch (error) { reject(error) }
    }),
  )
}
