<script setup>
// 调度建议面板（B-8 第二波组件化）：三态裁决/VLM 解释/方案摘要/审批门/监测与轮次账本/回放挂载。
// 纯展示层：读侧全走 props（计算仍归 App，hero/地图同源复用），写侧 7 个 v-model，
// 审批/监测/倍速以事件上抛——任务编排仍归 App。
// 2026-09-23 设计稿参考图第二版：hero 三态横幅 + 指标盒行 + 方案审批表单区；
// E2E 依赖的类名/按钮名/占位符全部原位保留（plan-summary/task-chips/people-risk/
// approval-actions/monitor-btn/sim-clock/monitor-result/round-list/replay-panel）。
import { computed } from 'vue'
import { Bot, RefreshCw, ShieldAlert, ShieldCheck, Timer } from 'lucide-vue-next'
import { replanTriggerLabel } from '../utils/labels'
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
  previewUrl: { type: String, default: '' },
  socWarnList: { type: Array, default: () => [] },
})
const plan = computed(() => props.result?.dispatch_plan || {})
// FE-75 视觉证据窗（审计§六步骤 3）：原图 + 真实检测框叠加 + 来源标注，研判阶段成为画面主角
const evidence = computed(() => {
  const data = props.result?.agent?.skill_chain?.fire_perception?.observation?.detector?.data || {}
  if (!props.previewUrl || data.mode !== 'real' || !Array.isArray(data.detections) || !data.detections.length) return null
  const width = Number(data.image_width) || 1920
  const height = Number(data.image_height) || 1080
  const boxes = data.detections.map((d) => {
    const [x1, y1, x2, y2] = d.box || [0, 0, 0, 0]
    return {
      cls: d.class_name,
      conf: Math.round((d.confidence || 0) * 100),
      left: `${(x1 / width) * 100}%`,
      top: `${(y1 / height) * 100}%`,
      width: `${((x2 - x1) / width) * 100}%`,
      height: `${((y2 - y1) / height) * 100}%`,
    }
  })
  return { image: props.previewUrl, boxes, source: data.source || 'detector', model: data.model || 'pwm-yolo', fire: boxes.filter((b) => b.cls === 'fire').length, smoke: boxes.filter((b) => b.cls === 'smoke').length }
})
// 调度结论指标盒（设计稿）：全部出自既有 plan/props，不引新口径
const metricBoxes = computed(() => {
  const selected = plan.value.selected_uavs || []
  return [
    { k: '预计控制时间', v: props.controlWindow, tone: props.controlVerdictView.tone === 'ok' ? 'ok' : 'warn' },
    { k: '建议出动', v: selected.length ? `${selected.length} 架 · ${selected.join('/')}` : `${plan.value.required_drones ?? '—'} 架` },
    { k: '方案版本', v: props.planVersionLabel || 'V1' },
    { k: 'SOC 返航约束', v: props.socWarnList.length ? `预警 ${props.socWarnList.join('、')}` : '满足', tone: props.socWarnList.length ? 'warn' : 'ok' },
    { k: '资源缺口', v: props.resourceGap.length ? props.resourceGap.map((gap) => gap.name || gap.resource || gap.type).join('、') : '无', tone: props.resourceGap.length ? 'bad' : 'ok' },
  ]
})
const peopleStatus = defineModel('peopleStatus', { type: String, default: 'unknown' })
const maxDrones = defineModel('maxDrones', { type: Number, default: 4 })
const targetMinutes = defineModel('targetMinutes', { type: Number, default: undefined })
const disabledUavs = defineModel('disabledUavs', { type: Array, default: () => [] })
const reasonInput = defineModel('reasonInput', { type: String, default: '' })
const simSpeed = defineModel('simSpeed', { type: Number, default: 1 })
const reportOpen = defineModel('reportOpen', { type: Boolean, default: false })
defineEmits(['approval', 'monitor', 'set-speed', 'error'])
</script>

<template>
  <section class="decision-panel panel">
    <div class="panel-heading"><h2>调度结论</h2><span class="ai-badge"><Bot :size="14" /> {{ dataMode }}</span></div>

    <!-- 三态裁决 hero（设计稿：绿 可控制 / 橙 维持压制 / 红 不可控制） -->
    <div class="decision-callout dp-hero" :class="'v-' + controlVerdictView.tone">
      <div class="decision-icon"><ShieldCheck v-if="controlVerdictView.tone === 'ok'" :size="22" /><Timer v-else-if="controlVerdictView.tone === 'mid'" :size="22" /><ShieldAlert v-else :size="22" /></div>
      <div class="dp-hero-text"><strong>{{ controlVerdictView.hero }}</strong><p>{{ result.explanation }}</p></div>
    </div>

    <!-- 指标盒行（预计控制时间 / 建议出动 / 方案版本 / SOC 返航 / 资源缺口） -->
    <div class="dp-metrics">
      <div v-for="box in metricBoxes" :key="box.k" class="dp-metric" :class="box.tone ? 'tone-' + box.tone : ''"><span>{{ box.k }}</span><b :title="box.v">{{ box.v }}</b></div>
    </div>

    <!-- 逐机任务分配 chips -->
    <div class="task-chips"><span v-for="task in result.dispatch_plan.tasks" :key="task.drone_id" :class="'tc-' + String(task.drone_id || '?').charAt(0)"><b>{{ task.drone_id }}</b> {{ task.task }}</span></div>

    <!-- 方案账本（E2E 依赖 .plan-summary 原文） -->
    <div class="plan-summary" v-if="analysisEnvelope && (analysisEnvelope?.status === 'awaiting_confirmation' || analysisEnvelope?.plan_versions?.length)"><b>方案 {{ planVersionLabel }}</b><span>FLP：{{ plan.fire_load_flp ?? result.dispatch_plan.fire_load_flp ?? '—' }}</span><span>时间区间：{{ controlWindow }}</span><span>硬约束：{{ plan.hard_constraints?.length ? plan.hard_constraints.join('、') : (plan.resource_gap?.some((gap) => gap.resource === 'hard_constraint') ? '存在冲突' : '满足') }}</span><span>缺口：{{ resourceGap.length ? resourceGap.map((gap) => gap.name || gap.resource || gap.type).join('、') : '无' }}</span><span>重规划：{{ plan.replan_trigger?.length ? plan.replan_trigger.map(replanTriggerLabel).join('、') : '未触发' }}</span><span v-if="evacuationSummary" class="evacuation-summary">疏散：{{ evacuationSummary }}</span><details class="plan-tech"><summary>技术明细（方案 ID · 备选 · 数据溯源）</summary><span>主方案：{{ currentPlanId || '当前方案' }}</span><span>备选：{{ plan.alternative_plan?.length ? `${plan.alternative_plan.length} 个` : '暂无' }}</span><span v-if="result.fire_params_source === 'demo_mapping'" class="src-note vlm-mapped">火情规模 ← 演示映射({{ result.fire_params_scale }}·{{ result.fire_params_mapping_version || 'demo-mapping-v1' }})· 标签随图变，数值出自映射约定</span><span v-if="result.fire_assessment?.fire_grid?.slope_source" class="src-note">FLP 输入 · 坡度←{{ result.fire_assessment.fire_grid.slope_source === 'environment' ? 'DEM 实测' : '场景' }} · 燃料←{{ result.fire_assessment.fire_grid.fuel_source === 'worldcover-fuel-v1' ? 'WorldCover 映射' : '场景' }} · K 值出自冻结配置</span><span class="src-note">数字来源 · FLP ← 火情负荷评估 · 时间区间 ← 离散轮次仿真 · 约束/缺口 ← 规则引擎硬约束校验</span></details></div>

    <!-- 视觉证据 / VLM 解释（E2E 依赖类名原位） -->
    <div v-if="evidence" class="evidence-window"><div class="ew-head"><b>视觉证据</b><span>{{ evidence.model }} · {{ evidence.source }} · 检测 {{ evidence.boxes.length }} 框（fire {{ evidence.fire }} / smoke {{ evidence.smoke }}）</span></div><div class="ew-stage"><img :src="evidence.image" alt="研判原始影像"><div v-for="(box, i) in evidence.boxes" :key="i" :class="['ew-box', 'ew-' + box.cls]" :style="{ left: box.left, top: box.top, width: box.width, height: box.height }"><em>{{ box.cls }} {{ box.conf }}%</em></div></div><p class="ew-note">检测框来自真实模型输出 · 视觉观察见下方 VLM 解释 · 数字出自规则引擎</p></div>
    <div v-if="vlmNote" class="vlm-note"><div class="vlm-note-head"><b>VLM 视觉解释</b><span class="src-note">{{ vlmNoteSource }}</span></div><p v-if="vlmNoteBody">{{ vlmNoteBody }}</p><p v-else class="muted">模型未返回摘要文本</p><div v-if="vlmNoteFacts.length" class="vlm-note-facts"><span v-for="(fact, i) in vlmNoteFacts" :key="i" :class="{ 'vlm-flag': fact === '需人工复核' }">{{ fact }}</span></div><ul v-if="vlmNoteIssues.length" class="vlm-note-issues"><li v-for="(issue, i) in vlmNoteIssues" :key="i">{{ issue }}</li></ul></div>
    <div v-if="frameTrendText" class="src-note frame-trend">{{ frameTrendText }}</div>
    <div v-if="inputProvenanceText" class="src-note">{{ inputProvenanceText }}</div>

    <!-- 方案审批（设计稿：约束表单 + 审批按钮组；.people-risk/.approval-actions E2E 原位） -->
    <div class="dp-approval" v-if="analysisId">
      <div class="dp-approval-head"><b>方案审批</b><small>人工审批门 · 调整后按约束重排方案</small></div>
      <div class="people-risk">
        <label>人员状态 <select v-model="peopleStatus"><option value="confirmed">有人</option><option value="absent">无人</option><option value="unknown">不确定</option></select></label>
        <label>出动上限 <select v-model.number="maxDrones" title="调整方案时生效的灭火机数量上限（可灭火机：E1-E6 + 多用途 S3/S4）"><option v-for="n in maxDronesOptions" :key="n" :value="n">{{ n }}</option></select></label>
        <label>时限 <input class="minute-input" type="number" min="1" v-model.number="targetMinutes" placeholder="min" title="调整方案时生效的目标处置时限（分钟）"></label>
        <label class="uav-disable">禁飞 <template v-for="uid in disableOptions" :key="uid"><input type="checkbox" :value="uid" v-model="disabledUavs"><span>{{ uid }}</span> </template></label>
        <span>{{ peopleRisk }}</span>
      </div>
      <div class="approval-actions">
        <input class="reason-input" v-model="reasonInput" placeholder="驳回/终止原因（必填）" aria-label="操作原因">
        <button class="primary dp-btn-approve" :disabled="approvalBusy" @click="$emit('approval', 'approve')">批准主方案</button>
        <button class="outline-btn" :disabled="approvalBusy" @click="$emit('approval', 'adjust')">按约束调整</button>
        <button class="outline-btn danger-btn" :disabled="approvalBusy" @click="$emit('approval', 'reject')">驳回</button>
        <button class="outline-btn danger-btn" :disabled="approvalBusy" @click="$emit('approval', 'terminate')">终止任务</button>
        <button class="outline-btn" @click="reportOpen = !reportOpen">{{ reportOpen ? '收起报告' : '在线查看报告' }}</button>
        <a v-if="analysisId" class="outline-btn" :href="`/api/tasks/${analysisId}/report/export`" download title="独立 HTML 图文报告，浏览器打开后可打印为 PDF">导出图文报告</a>
      </div>
    </div>
    <ReportViewer v-if="reportOpen" :analysis-id="analysisId" :verdict-report="controlVerdictView.report" @error="$emit('error', $event)" />

    <!-- 轮次推演 -->
    <div class="dp-monitor-row">
      <button v-if="analysisResult" class="monitor-btn" :disabled="monitoring" @click="$emit('monitor')"><RefreshCw :size="14" /> {{ monitoring ? '推演中…' : '执行下一轮监测' }}</button>
      <span v-if="missionActive" class="sim-clock">自动推演 · 第 {{ Math.min(Math.floor(missionNow / 5) + 1, activeRounds.length + 1) }} 轮 · {{ Math.floor(missionNow % 5) }}/5 min</span>
      <label v-if="missionActive" class="sim-speed" title="推演速度倍率">速度 <select v-model.number="simSpeed" @change="$emit('set-speed', simSpeed)"><option :value="1">1×</option><option :value="2">2×</option><option :value="4">4×</option></select></label>
    </div>
    <div v-if="monitorResult" class="monitor-result"><span class="mr-head">第 {{ analysisEnvelope?.monitor_round || activeRounds.length }} 轮 · 监测结果</span><span class="mr-cell"><small>火焰面积</small><b>{{ monitorArea }}m²</b></span><span class="mr-cell"><small>FLP</small><b>{{ monitorResult.fire_load_flp ?? monitorResult.next_fire_load_flp ?? '—' }}</b></span><span class="mr-cell mr-wide"><small>SOC</small><b :title="monitorResult.next_fleet?.map((drone) => `${drone.id}:${drone.soc ?? drone.battery}%`).join('、')">{{ monitorResult.next_fleet?.length ? monitorResult.next_fleet.slice(0, 4).map((drone) => `${drone.id}:${drone.soc ?? drone.battery}%`).join('、') + (monitorResult.next_fleet.length > 4 ? ` 等 ${monitorResult.next_fleet.length} 架` : '') : '—' }}</b></span><span class="mr-cell mr-wide"><small>库存</small><b>{{ monitorResult.next_inventory ? `水 ${monitorResult.next_inventory.water_liters ?? 0}L / W20×${monitorResult.next_inventory.water_modules_w20 ?? 0} / C6×${monitorResult.next_inventory.co2_modules_c6 ?? 0} / 电池×${monitorResult.next_inventory.battery_packs ?? 0}` : '—' }}</b></span><span class="mr-reason">{{ monitorResult.reason || '无重规划原因' }}</span></div>
    <div v-if="activeRounds.length" class="round-list"><div v-for="round in activeRounds" :key="round.round || round.monitor_round"><b>第 {{ round.round || round.monitor_round }} 轮</b><span>轮前 {{ round.before?.fire_load_flp ?? round.before?.fire_load ?? '—' }}</span><span>轮后 {{ round.after?.fire_load_flp ?? round.after?.fire_load ?? '—' }}</span><span>触发：{{ (round.replan_triggers || round.replan_trigger || []).map(replanTriggerLabel).join('、') || '无' }}</span><span v-if="round.after?.flp_ledger" class="round-ledger">净 {{ round.after.flp_ledger.net_change_flp ?? '—' }} FLP（增长 {{ round.after.flp_ledger.growth_flp ?? '—' }} · 压制 {{ round.after.flp_ledger.suppression_flp ?? '—' }}）</span><span v-if="round.next_action">动作 {{ round.next_action === 'awaiting_confirmation' ? '等待二次审批' : round.next_action === 'finish' ? '火情扑灭·结案' : round.next_action }}</span></div></div>
    <ReplayPanel v-if="activeRounds.length" :rounds="activeRounds" :area-per-flp="result?.fire_assessment?.area_per_flp || 0" />
  </section>
</template>
