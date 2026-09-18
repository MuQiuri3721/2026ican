<script setup>
// 调度建议面板（B-8 第二波组件化）：三态裁决/VLM 解释/方案摘要/审批门/监测与轮次账本/回放挂载。
// 纯展示层：读侧全走 props（计算仍归 App，hero/地图同源复用），写侧 7 个 v-model，
// 审批/监测/倍速以事件上抛——任务编排仍归 App。
import { computed } from 'vue'
import { Bot, RefreshCw, ShieldAlert, ShieldCheck, Timer } from 'lucide-vue-next'
import ReportViewer from './ReportViewer.vue'
import ReplayPanel from './ReplayPanel.vue'

const props = defineProps({
  analysisResult: { type: Object, default: null },
  disableOptions: { type: Array, default: () => [] },
  maxDronesOptions: { type: Number, default: 4 },
  result: { type: Object, default: () => ({}) },
  analysisEnvelope: { type: Object, default: null },
  analysisId: { type: String, default: '' },
  activeRounds: { type: Array, default: () => [] },
  monitorResult: { type: Object, default: null },
  monitorArea: { type: [Number, String], default: null },
  dataMode: { type: String, default: '' },
  controlVerdictView: { type: Object, required: true },
  planVersionLabel: { type: String, default: '' },
  currentPlanId: { type: String, default: '' },
  controlWindow: { type: String, default: '—' },
  resourceGap: { type: Array, default: () => [] },
  evacuationSummary: { type: String, default: '' },
  peopleRisk: { type: String, default: '' },
  vlmNote: { type: Object, default: null },
  vlmNoteSource: { type: String, default: '' },
  vlmNoteBody: { type: String, default: '' },
  vlmNoteFacts: { type: Array, default: () => [] },
  vlmNoteIssues: { type: Array, default: () => [] },
  frameTrendText: { type: String, default: '' },
  inputProvenanceText: { type: String, default: '' },
  missionActive: { type: Boolean, default: false },
  missionNow: { type: Number, default: 0 },
  approvalBusy: { type: Boolean, default: false },
  monitoring: { type: Boolean, default: false },
})
const plan = computed(() => props.result?.dispatch_plan || {})
const peopleStatus = defineModel('peopleStatus', { type: String, default: 'unknown' })
const maxDrones = defineModel('maxDrones', { type: Number, default: 4 })
const targetMinutes = defineModel('targetMinutes', { type: Number, default: undefined })
const disabledUavs = defineModel('disabledUavs', { type: Array, default: () => [] })
const reasonInput = defineModel('reasonInput', { type: String, default: '' })
const simSpeed = defineModel('simSpeed', { type: Number, default: 1 })
const reportOpen = defineModel('reportOpen', { type: Boolean, default: false })
defineEmits(['approval', 'monitor', 'set-speed', 'error'])
</script>

<template>        <section class="decision-panel panel"><div class="panel-heading"><h2>调度建议</h2><span class="ai-badge"><Bot :size="14" /> {{ dataMode }}</span></div><div class="decision-callout"><div class="decision-icon" :class="'v-' + controlVerdictView.tone"><ShieldCheck v-if="controlVerdictView.tone === 'ok'" :size="20" /><Timer v-else-if="controlVerdictView.tone === 'mid'" :size="20" /><ShieldAlert v-else :size="20" /></div><div><strong>{{ controlVerdictView.callout }}</strong><p>{{ result.explanation }}</p></div></div><div v-if="vlmNote" class="vlm-note"><div class="vlm-note-head"><b>VLM 视觉解释</b><span class="src-note">{{ vlmNoteSource }}</span></div><p v-if="vlmNoteBody">{{ vlmNoteBody }}</p><p v-else class="muted">模型未返回摘要文本</p><div v-if="vlmNoteFacts.length" class="vlm-note-facts"><span v-for="(fact, i) in vlmNoteFacts" :key="i" :class="{ 'vlm-flag': fact === '需人工复核' }">{{ fact }}</span></div><ul v-if="vlmNoteIssues.length" class="vlm-note-issues"><li v-for="(issue, i) in vlmNoteIssues" :key="i">{{ issue }}</li></ul></div><div v-if="frameTrendText" class="src-note frame-trend">{{ frameTrendText }}</div><div v-if="inputProvenanceText" class="src-note">{{ inputProvenanceText }}</div><div class="plan-summary" v-if="analysisEnvelope && (analysisEnvelope?.status === 'awaiting_confirmation' || analysisEnvelope?.plan_versions?.length)"><b>方案 {{ planVersionLabel }}</b><span>FLP：{{ plan.fire_load_flp ?? result.dispatch_plan.fire_load_flp ?? '—' }}</span><span>主方案：{{ currentPlanId || '当前方案' }}</span><span>时间区间：{{ controlWindow }}</span><span>硬约束：{{ plan.hard_constraints?.length ? plan.hard_constraints.join('、') : (plan.resource_gap?.some((gap) => gap.resource === 'hard_constraint') ? '存在冲突' : '满足') }}</span><span>备选：{{ plan.alternative_plan?.length ? `${plan.alternative_plan.length} 个` : '暂无' }}</span><span>缺口：{{ resourceGap.length ? resourceGap.map((gap) => gap.name || gap.resource || gap.type).join('、') : '无' }}</span><span>重规划：{{ plan.replan_trigger?.length ? plan.replan_trigger.join('、') : '未触发' }}</span><span v-if="evacuationSummary" class="evacuation-summary">疏散：{{ evacuationSummary }}</span><span v-if="result.fire_params_source === 'demo_mapping'" class="src-note vlm-mapped">火情规模 ← 演示映射({{ result.fire_params_scale }}·{{ result.fire_params_mapping_version || 'demo-mapping-v1' }})· 标签随图变，数值出自映射约定</span><span v-if="result.fire_assessment?.fire_grid?.slope_source" class="src-note">FLP 输入 · 坡度←{{ result.fire_assessment.fire_grid.slope_source === 'environment' ? 'DEM 实测' : '场景' }} · 燃料←{{ result.fire_assessment.fire_grid.fuel_source === 'worldcover-fuel-v1' ? 'WorldCover 映射' : '场景' }} · K 值出自冻结配置</span><span class="src-note">数字来源 · FLP ← 火情负荷评估 · 时间区间 ← 离散轮次仿真 · 约束/缺口 ← 规则引擎硬约束校验</span></div><div class="people-risk"><label>人员状态 <select v-model="peopleStatus"><option value="confirmed">有人</option><option value="absent">无人</option><option value="unknown">不确定</option></select></label><label>出动上限 <select v-model.number="maxDrones" title="调整方案时生效的灭火机数量上限（可灭火机：E1-E6 + 多用途 S3/S4）"><option v-for="n in maxDronesOptions" :key="n" :value="n">{{ n }}</option></select></label><label>时限 <input class="minute-input" type="number" min="1" v-model.number="targetMinutes" placeholder="min" title="调整方案时生效的目标处置时限（分钟）"></label><label class="uav-disable">禁用 <template v-for="uid in disableOptions" :key="uid"><input type="checkbox" :value="uid" v-model="disabledUavs"><span>{{ uid }}</span> </template></label><span>{{ peopleRisk }}</span></div><div class="approval-actions" v-if="analysisId"><input class="reason-input" v-model="reasonInput" placeholder="驳回/终止原因（必填）" aria-label="操作原因"><button class="outline-btn" :disabled="approvalBusy" @click="$emit('approval', 'approve')">批准主方案</button><button class="outline-btn" :disabled="approvalBusy" @click="$emit('approval', 'adjust')">按约束调整</button><button class="outline-btn danger-btn" :disabled="approvalBusy" @click="$emit('approval', 'reject')">驳回</button><button class="outline-btn danger-btn" :disabled="approvalBusy" @click="$emit('approval', 'terminate')">终止任务</button><button class="outline-btn" @click="reportOpen = !reportOpen">{{ reportOpen ? '收起报告' : '在线查看报告' }}</button><a v-if="analysisId" class="outline-btn" :href="`/api/tasks/${analysisId}/report/export`" download title="独立 HTML 图文报告，浏览器打开后可打印为 PDF">导出图文报告</a></div><ReportViewer v-if="reportOpen" :analysis-id="analysisId" :verdict-report="controlVerdictView.report" @error="$emit('error', $event)" /><div class="task-chips"><span v-for="task in result.dispatch_plan.tasks" :key="task.drone_id" :class="'tc-' + String(task.drone_id || '?').charAt(0)"><b>{{ task.drone_id }}</b> {{ task.task }}</span></div><button v-if="analysisResult" class="monitor-btn" :disabled="monitoring" @click="$emit('monitor')"><RefreshCw :size="14" /> {{ monitoring ? '推演中…' : '执行下一轮监测' }}</button><span v-if="missionActive" class="sim-clock">自动推演 · 第 {{ Math.min(Math.floor(missionNow / 5) + 1, activeRounds.length + 1) }} 轮 · {{ Math.floor(missionNow % 5) }}/5 min</span><label v-if="missionActive" class="sim-speed" title="推演速度倍率">速度 <select v-model.number="simSpeed" @change="$emit('set-speed', simSpeed)"><option :value="1">1×</option><option :value="2">2×</option><option :value="4">4×</option></select></label><div v-if="monitorResult" class="monitor-result"><span class="mr-head">第 {{ analysisEnvelope?.monitor_round || activeRounds.length }} 轮 · 监测结果</span><span class="mr-cell"><small>火焰面积</small><b>{{ monitorArea }}m²</b></span><span class="mr-cell"><small>FLP</small><b>{{ monitorResult.fire_load_flp ?? monitorResult.next_fire_load_flp ?? '—' }}</b></span><span class="mr-cell mr-wide"><small>SOC</small><b>{{ monitorResult.next_fleet?.map((drone) => `${drone.id}:${drone.soc ?? drone.battery}%`).join('、') || '—' }}</b></span><span class="mr-cell mr-wide"><small>库存</small><b>{{ monitorResult.next_inventory ? `水 ${monitorResult.next_inventory.water_liters ?? 0}L / W20×${monitorResult.next_inventory.water_modules_w20 ?? 0} / C6×${monitorResult.next_inventory.co2_modules_c6 ?? 0} / 电池×${monitorResult.next_inventory.battery_packs ?? 0}` : '—' }}</b></span><span class="mr-reason">{{ monitorResult.reason || '无重规划原因' }}</span></div><div v-if="activeRounds.length" class="round-list"><div v-for="round in activeRounds" :key="round.round || round.monitor_round"><b>Round {{ round.round || round.monitor_round }}</b><span>before FLP {{ round.before?.fire_load_flp ?? round.before?.fire_load ?? '—' }}</span><span>after FLP {{ round.after?.fire_load_flp ?? round.after?.fire_load ?? '—' }}</span><span>触发原因：{{ (round.replan_triggers || round.replan_trigger || []).join('、') || '无' }}</span><span v-if="round.after?.flp_ledger" class="round-ledger">净 {{ round.after.flp_ledger.net_change_flp ?? '—' }} FLP（增长 {{ round.after.flp_ledger.growth_flp ?? '—' }} · 压制 {{ round.after.flp_ledger.suppression_flp ?? '—' }}）</span><span v-if="round.next_action">动作 {{ round.next_action === 'awaiting_confirmation' ? '等待二次审批' : round.next_action === 'finish' ? '火情扑灭·结案' : round.next_action }}</span></div></div><ReplayPanel v-if="activeRounds.length" :rounds="activeRounds" :area-per-flp="result?.fire_assessment?.area_per_flp || 0" /></section>
</template>
