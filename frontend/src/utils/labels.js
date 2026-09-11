/* 展示层标签换算：后端枚举/机读值 → 中文界面文案。纯函数，无状态。 */
import { AGENT_MSG_LABELS, AGENT_SOURCE_LABELS, MODULE_LABELS, STREAM_TYPE_META } from '../constants'

export function agentMsgLabel(type) {
  return AGENT_MSG_LABELS[type] || type
}

export function agentSourceLabel(source) {
  return AGENT_SOURCE_LABELS[source] || source || '规则'
}

export function moduleLabel(module) {
  return MODULE_LABELS[module] || module || '—'
}

export function formatNumber(value) {
  return new Intl.NumberFormat('zh-CN').format(value)
}

export function issueText(item) {
  if (item == null) return ''
  if (typeof item === 'string') return item
  if (typeof item === 'object') return item.message || item.description || item.reason || ''
  return String(item)
}

export function streamType(log) {
  const stage = typeof log === 'object' ? log.stage : ''
  const meta = STREAM_TYPE_META[stage]
  return meta ? { label: meta[0], color: meta[1] } : { label: stage || '事件', color: '#8fa39a' }
}

export function waterTypeClass(typeText) {
  const t = String(typeText || '')
  if (t.includes('水库')) return 'reservoir'
  if (t.includes('湖')) return 'lake'
  if (t.includes('河')) return 'river'
  if (t.includes('塘')) return 'pond'
  return 'water'
}

export function waterTypeLabel(water) {
  const type = String(water?.type || water?.water_type || water?.category || '').toLowerCase()
  if (type.includes('lake') || type.includes('湖')) return '湖泊'
  if (type.includes('reservoir') || type.includes('水库')) return '水库'
  if (type.includes('river') || type.includes('河')) return '河流'
  if (type.includes('pond') || type.includes('塘')) return '池塘'
  return water?.type || water?.water_type || '水源'
}

export function logText(log) {
  return typeof log === 'string' ? log : log.message
}

export function logTime(log, index) {
  if (typeof log === 'object' && log.timestamp) return log.timestamp.slice(11, 19)
  return `09:${String(20 - index).padStart(2, '0')}`
}
