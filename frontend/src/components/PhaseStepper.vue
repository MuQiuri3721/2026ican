<script setup>
// 任务阶段轨（FE-19，交互范式参考 firepatrol-agents PhaseStepper）：
// 由后端任务状态驱动 7 段推进；done=true 全绿收卷，dead=true 终态染红，重规划次数显性化。
import { Archive, Bot, Eye, FileImage, Gauge, Radio, ShieldCheck } from 'lucide-vue-next'

defineProps({
  stage: { type: Number, default: -1 },
  done: { type: Boolean, default: false },
  dead: { type: Boolean, default: false },
  replans: { type: Number, default: 0 },
})

const STAGES = [
  { no: '01', label: '接入', icon: FileImage },
  { no: '02', label: '感知', icon: Eye },
  { no: '03', label: '研判', icon: Bot },
  { no: '04', label: '方案', icon: Gauge },
  { no: '05', label: '审批', icon: ShieldCheck },
  { no: '06', label: '执行', icon: Radio },
  { no: '07', label: '归档', icon: Archive },
]
</script>

<template>
  <div :class="['ph-step', { 'ph-dead': dead }]" role="list" aria-label="任务阶段">
    <div
      v-for="(item, i) in STAGES"
      :key="item.no"
      :class="['ph-stage', { 'ph-done': done || i < stage, 'ph-active': !done && i === stage }]"
      role="listitem"
    >
      <span class="ph-no">{{ item.no }}</span>
      <span class="ph-node">
        <template v-if="done || i < stage">✓</template>
        <component :is="item.icon" v-else :size="14" />
      </span>
      <span class="ph-label">{{ item.label }}</span>
      <span v-if="i < STAGES.length - 1" class="ph-link" />
    </div>
    <span v-if="replans > 0" class="ph-replan" title="执行中触发重规划，已回到方案阶段">↺ 重规划 ×{{ replans }}</span>
  </div>
</template>
