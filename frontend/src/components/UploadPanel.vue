<script setup>
// 现场影像接入面板（B-8 第二波组件化）：拖拽/选文件、分析管线进度、模型状态、
// 演训模拟入口。文件接收（acceptFile）与研判/演训编排仍在 App——本组件只发意图。
import { ref } from 'vue'
import { Bot, ChevronRight, FileImage, RefreshCw, Upload } from 'lucide-vue-next'

defineProps({
  analyzing: { type: Boolean, default: false },
  progress: { type: Number, default: 0 },
  uploaded: { type: Boolean, default: false },
  previewUrl: { type: String, default: '' },
  selectedFile: { type: Object, default: null },
  selectedFrames: { type: Array, default: () => [] },
  projectStatus: { type: Object, default: () => ({}) },
  environmentCoordinates: { type: Object, default: () => ({ latitude: 32.0725, longitude: 118.8415 }) },
  scenario: { type: Object, default: null },
  scenarioBusy: { type: Boolean, default: false },
})
const useVlm = defineModel('useVlm', { type: Boolean, default: false })
const emit = defineEmits(['files', 'reset', 'generate-scenario', 'start-scenario'])

const fileInput = ref(null)

function openFilePicker() {
  fileInput.value?.click()
}

function onFileChange(event) {
  emit('files', event.target.files)
  event.target.value = ''
}

function onDrop(event) {
  emit('files', event.dataTransfer.files)
}
</script>

<template>
  <section class="upload-panel"><div class="panel-heading"><h2>现场影像接入</h2><FileImage :size="19" class="muted-icon" /></div><input ref="fileInput" class="visually-hidden" type="file" accept="image/jpeg,image/png,video/mp4" multiple @change="onFileChange"><div class="dropzone" :class="{ uploaded }" @click="openFilePicker" @dragover.prevent @drop.prevent="onDrop"><div v-if="previewUrl && selectedFile?.type.startsWith('image/')" class="preview-thumb"><img :src="previewUrl" alt="已选择的火灾影像预览"></div><div v-else class="upload-orb"><Upload :size="22" /></div><strong>{{ uploaded ? (selectedFrames.length ? `影像已接入 · 序列 ${selectedFrames.length + 1} 帧` : '影像已接入') : '拖入航拍图像或视频' }}</strong><span>{{ uploaded ? `${selectedFile.name}${selectedFrames.length ? ` + ${selectedFrames.length} 帧序列` : ''} · ${(selectedFile.size / 1024 / 1024).toFixed(1)} MB` : '支持 JPG / PNG / MP4 · 多选图片组成序列 · 最大 200MB' }}</span><button type="button" @click.stop="openFilePicker">{{ uploaded ? '更换文件' : '选择文件' }}</button></div><div class="process"><div class="process-row"><span>分析管线</span><b>{{ progress }}%</b></div><div class="progress"><i :style="{ width: progress + '%' }"></i></div><div class="pipeline"><span :class="{ done: progress >= 24 }">视觉识别</span><ChevronRight :size="13" /><span :class="{ done: progress >= 48 }">环境融合</span><ChevronRight :size="13" /><span :class="{ done: progress >= 72 }">风险评估</span><ChevronRight :size="13" /><span :class="{ done: progress >= 90 }">调度生成</span></div><div class="model-status"><span title="YOLO 检测接收面已就绪（协议+mock 全链验证），真实 PWM-YOLO 权重到位即插即用">YOLO <b>{{ projectStatus.yolo === 'pending' ? '对接就绪' : projectStatus.yolo === 'configured' ? '已配置' : '在线' }}</b></span><span>VLM <b>{{ projectStatus.vlm === 'pending' ? '待接入' : projectStatus.vlm === 'configured' ? '已配置' : '在线' }}</b></span><span>场景数据 <b>{{ projectStatus.geo_data }}</b></span><label class="vlm-toggle"><input type="checkbox" v-model="useVlm"> 上传时调用 VLM 解释</label></div><div class="fire-coord-note">火点将定位至 <b>{{ environmentCoordinates.longitude.toFixed(6) }}°E, {{ environmentCoordinates.latitude.toFixed(6) }}°N</b> · 可在地图「指定火点」选点或在现场环境面板输入坐标修改</div></div><button v-if="uploaded" class="reset-link" @click="emit('reset')"><RefreshCw :size="13" /> 清空并重新接入</button><div class="scenario-block"><div class="scenario-head"><b>演训模拟</b><small>无需影像 · 随机生成紫金山火情</small></div><div v-if="!scenario" class="scenario-empty">点击生成一处在紫金山范围内随机出现的火情，随后开始模拟集群调度推演。</div><div v-else class="scenario-facts"><span>火点 <b>{{ scenario.fireGps.longitude }}°E, {{ scenario.fireGps.latitude }}°N</b></span><span>面积 <b>{{ scenario.areaM2 }} m²</b></span><span>增长率 <b>{{ scenario.growthRate }}/h</b></span><span>人员 <b>{{ scenario.people === 'confirmed' ? '在场' : scenario.people === 'absent' ? '不在场' : '情况不明' }}</b></span><span v-if="scenario.failureRound" class="scenario-drill">⚔ 含单机失能演练（第 {{ scenario.failureRound }} 轮）</span><span v-if="scenario.windShift" class="scenario-drill">🌪 风变演练（第 {{ scenario.windShift.round }} 轮 · {{ scenario.windShift.speed }} m/s）</span></div><div class="scenario-actions"><button class="outline-btn" :disabled="scenarioBusy || analyzing" @click="emit('generate-scenario')">{{ scenario ? '重新生成火情' : '生成随机火情' }}</button><button v-if="scenario" class="primary scenario-start" :disabled="scenarioBusy || analyzing" @click="emit('start-scenario')"><Bot :size="16" /> 开始模拟</button></div></div></section>
</template>
