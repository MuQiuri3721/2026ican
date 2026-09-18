<script setup>
// 历史任务面板（B-8 第二波组件化）：任务列表 + 对比勾选 + ComparePanel 挂载。
// 列表数据由父级拉取（props.tasks），行恢复/刷新以事件上抛——任务编排仍归 App。
import { ref, watch } from 'vue'
import { RefreshCw } from 'lucide-vue-next'
import ComparePanel from './ComparePanel.vue'

defineProps({
  tasks: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['restore', 'refresh', 'error'])

const compareSel = ref([])
const compareOpen = ref(false)
watch(compareSel, (next) => {
  if (next.length > 4) compareSel.value = next.slice(-4)
  if (next.length < 2) compareOpen.value = false
})
</script>

<template>
  <section class="detail-view"><div class="detail-heading"><div><h2>历史任务</h2><p>任务记录来自后端 /api/analyzes，点击任务可恢复主显示结果。勾选 2–4 个任务可横向对比。{{ tasks.length > 50 ? " 最近 50 条优先显示" : "" }}</p></div><button v-if="compareSel.length >= 2" class="outline-btn" @click="compareOpen = !compareOpen">{{ compareOpen ? '收起对比' : `对比所选（${compareSel.length}）` }}</button><button class="outline-btn" @click="emit('refresh')"><RefreshCw :size="14" /> 刷新</button></div><ComparePanel v-if="compareOpen && compareSel.length >= 2" :ids="compareSel" @error="emit('error', $event)" /><div class="full-logs"><div v-if="loading"><div class="skeleton-row"></div><div class="skeleton-row"></div><div class="skeleton-row"></div></div><div v-else-if="!tasks.length" class="empty-hint"><b>还没有历史任务</b>点击右上角「开始任务」上传影像，完成研判后任务会自动归档到这里。</div><div v-for="task in tasks.slice(0, 50)" :key="task.analysis_id" class="history-row" @click="emit('restore', task)"><label class="cmp-pick" title="勾选参与对比（2–4 个）" @click.stop><input type="checkbox" :value="task.analysis_id" v-model="compareSel"><span>比</span></label><span class="log-time">{{ task.created_at?.slice(0, 19).replace('T', ' ') }}</span><i></i><span><strong>{{ task.analysis_id }}</strong> · {{ task.input?.image_name || '未命名影像' }}</span><small>{{ task.status }}</small></div></div></section>
</template>
