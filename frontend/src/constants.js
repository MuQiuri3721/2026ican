/* 全局常量：标签映射、任务推演参数、锚点。纯数据，不含行为。 */

export const ZIXIAHU_BASE_GPS = { latitude: 32.062229, longitude: 118.839016 }

export const MISSION_MS_PER_MIN = 1200 // 1 仿真分钟 ≈ 1.2 实秒（一轮 5 仿真分钟 ≈ 6s）
export const MISSION_ROUND_MS = 6000
export const MISSION_PHASE_LABELS = { flying: '出动中', working: '喷洒作业', returning: '返航中', servicing: '基地补水', charging: '基地充电', orbit: '侦察盘旋', parked: '待命' }

export const TTS_VOICE = 'zh-CN-XiaoxiaoNeural'

export const statusLabels = { succeeded: '已完成', completed: '已完成', running: '执行中', awaiting_confirmation: '待确认', approved: '已批准', executing: '执行中', replanning: '重规划中', terminated: '已终止', action_required: '需要处置', failed: '失败', queued: '排队中', available: '待命', assigned: '已分配', flying: '飞行中', working: '作业中', returning: '返航中', servicing: '维护中', charging: '充电中', fault: '故障', offline: '离线' }

export const AGENT_MSG_LABELS = { TASK_ASSIGN: '建案派任务', FINDING: '态势发现', PLAN_PROPOSAL: '方案提案', SIM_RESULT: '仿真评估', APPROVAL_REQ: '审批请求', APPROVAL_DECISION: '审批仲裁', JUDGMENT: '自主研判', REPLAN_TRIGGER: '重规划触发', REPORT: '结案报告', EVAC_BROADCAST: '疏散广播', UAV_FAULT: '单机失能', BACKFILL: '补位接替', RECOVERY: '结案回收', INFO: '信息', ERROR: '异常' }

export const AGENT_SOURCE_LABELS = { glm: 'GLM 在线', 'conservative-fallback': '保守降级', 'deterministic-offline': '规则离线', rules: '规则引擎', agent: 'Agent', user: '指挥员', 'parse-failed': '解析回退' }

export const VLM_ERROR_LABELS = {
  rate_limited: '免费档限流(429)，稍后重传可获真实识别',
  auth_failed: '鉴权失败，请检查 FIRE_VLM_API_KEY',
  timeout_or_network: '网络超时或不可达',
  empty_response: '模型返回空响应',
  invalid_response: '模型响应异常',
}

export const MODULE_LABELS = { none: '无载荷', water_20l: '水剂 20L', co2_6kg: 'CO₂ 6kg', sup_10: '补给 10kg' }

export const LAYER_LABELS = { fire: '火点', water: '水源', road: '道路', drone: '无人机', contour: '等高线', evacuation: '疏散路线' }

export const SUBGROUP_COLORS = { reconnaissance: '#7fb3ff', suppression: '#e07856', support: '#5fbd92' }

export const STREAM_TYPE_META = {
  system: ['系统', '#8fa39a'], scene: ['场景', '#7fb3ff'], fleet: ['集群', '#5fbd92'], ui: ['操作', '#b9a3e0'],
  monitor: ['监测', '#f0a848'], mission: ['出动', '#e07856'], scenario: ['演训', '#e2b95d'], rules: ['规则引擎', '#5fbd92'],
  perception: ['感知', '#7fb3ff'], analysis: ['研判', '#7fb3ff'], dispatch: ['调度', '#e07856'], approval: ['审批', '#f0a848'],
}

export const FLEET_GROUP_META = [
  { key: 'reconnaissance', label: '侦察单元', role: '火情侦察与态势回传' },
  { key: 'suppression', label: '灭火单元', role: '主力灭火 · 水剂 / 干粉模块' },
  { key: 'support', label: '支援单元', role: '物资补给与中继保障' },
]
