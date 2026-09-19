<script setup>
// 现场影像接入面板（B-8 第二波组件化）：拖拽/选文件、分析管线进度、模型状态、
// 演训模拟入口。文件接收（acceptFile）与研判/演训编排仍在 App——本组件只发意图。
import { nextTick, onBeforeUnmount, ref } from 'vue'
import { Bot, Camera, ChevronRight, FileImage, RefreshCw, Upload } from 'lucide-vue-next'

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
  detectorStatus: { type: Object, default: null },
})
const useVlm = defineModel('useVlm', { type: Boolean, default: false })
const emit = defineEmits(['files', 'reset', 'generate-scenario', 'start-scenario', 'capture', 'demo-main', 'demo-perturb'])

const fileInput = ref(null)

// —— 现场采集（阶段二）：USB 相机/网络视频流抓一帧 → 自动进入真实检测→VLM→调度 ——
const cameraOn = ref(false)
const cameraError = ref('')
const videoRef = ref(null)
let cameraStream = null
async function openCamera() {
  cameraError.value = ''
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 } } })
    cameraOn.value = true
    await nextTick()
    if (videoRef.value) videoRef.value.srcObject = cameraStream
  } catch (error) {
    cameraError.value = '无法访问摄像头 · ' + (error?.message || error)
  }
}
async function captureFrame() {
  const video = videoRef.value
  if (!video) return
  // 视频流就绪等待（round21 抓出：秒点抓帧时 videoWidth 仍为 0，静默无效果）
  for (let waited = 0; waited < 30 && !video.videoWidth; waited += 1) {
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  if (!video.videoWidth) { cameraError.value = '相机尚未就绪，请稍后重试。'; return }
  const canvas = document.createElement('canvas')
  canvas.width = video.videoWidth
  canvas.height = video.videoHeight
  canvas.getContext('2d').drawImage(video, 0, 0)
  canvas.toBlob((blob) => {
    stopCamera()
    if (!blob) return
    const stamp = new Date().toISOString().slice(11, 19).replaceAll(':', '')
    emit('capture', new File([blob], `现场采集-${stamp}.jpg`, { type: 'image/jpeg' }))
  }, 'image/jpeg', 0.92)
}
function stopCamera() {
  if (cameraStream) { cameraStream.getTracks().forEach((track) => track.stop()); cameraStream = null }
  cameraOn.value = false
}
onBeforeUnmount(stopCamera)

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
  <section class="upload-panel"><div class="panel-heading"><h2>现场影像接入</h2><FileImage :size="19" class="muted-icon" /></div><input ref="fileInput" class="visually-hidden" type="file" accept="image/jpeg,image/png,video/mp4" multiple @change="onFileChange"><div class="dropzone" :class="{ uploaded }" @click="openFilePicker" @dragover.prevent @drop.prevent="onDrop"><div v-if="previewUrl && selectedFile?.type.startsWith('image/')" class="preview-thumb"><img :src="previewUrl" alt="已选择的火灾影像预览"></div><div v-else class="upload-orb"><Upload :size="22" /></div><strong>{{ uploaded ? (selectedFrames.length ? `影像已接入 · 序列 ${selectedFrames.length + 1} 帧` : '影像已接入') : '拖入航拍图像或视频' }}</strong><span>{{ uploaded ? `${selectedFile.name}${selectedFrames.length ? ` + ${selectedFrames.length} 帧序列` : ''} · ${(selectedFile.size / 1024 / 1024).toFixed(1)} MB` : '支持 JPG / PNG / MP4 · 多选图片组成序列 · 最大 200MB' }}</span><button type="button" @click.stop="openFilePicker">{{ uploaded ? '更换文件' : '选择文件' }}</button><button type="button" class="capture-btn" @click.stop="openCamera"><Camera :size="14" /> 现场采集</button></div><div v-if="cameraOn" class="camera-pane"><video ref="videoRef" autoplay playsinline muted></video><div class="camera-actions"><button type="button" class="primary" @click.stop="captureFrame">抓帧并研判</button><button type="button" class="outline-btn" @click.stop="stopCamera">取消</button></div></div><p v-else-if="cameraError" class="camera-error">{{ cameraError }}</p><div class="process"><div class="process-row"><span>分析管线</span><b>{{ progress }}%</b></div><div class="progress"><i :style="{ width: progress + '%' }"></i></div><div class="pipeline"><span :class="{ done: progress >= 24 }">视觉识别</span><ChevronRight :size="13" /><span :class="{ done: progress >= 48 }">环境融合</span><ChevronRight :size="13" /><span :class="{ done: progress >= 72 }">风险评估</span><ChevronRight :size="13" /><span :class="{ done: progress >= 90 }">调度生成</span></div><div class="model-status"><span title="YOLO 检测接收面已就绪（协议+mock 全链验证），真实 PWM-YOLO 权重到位即插即用">YOLO <b>{{ projectStatus.yolo === 'pending' ? '对接就绪' : projectStatus.yolo === 'configured' ? '已配置' : '在线' }}</b></span><span>VLM <b>{{ projectStatus.vlm === 'pending' ? '待接入' : projectStatus.vlm === 'configured' ? '已配置' : '在线' }}</b></span><span>场景数据 <b>{{ projectStatus.geo_data }}</b></span><span v-if="detectorStatus" class="detector-live" title="本次研判的真实检测结果来源">YOLO <b>{{ detectorStatus.mode }}</b> · {{ detectorStatus.model }} · {{ detectorStatus.source }}</span><label class="vlm-toggle"><input type="checkbox" v-model="useVlm"> 上传时调用 VLM 解释</label></div><div class="fire-coord-note">火点将定位至 <b>{{ environmentCoordinates.longitude.toFixed(6) }}°E, {{ environmentCoordinates.latitude.toFixed(6) }}°N</b> · 可在地图「指定火点」选点或在现场环境面板输入坐标修改</div></div><button v-if="uploaded" class="reset-link" @click="emit('reset')"><RefreshCw :size="13" /> 清空并重新接入</button><div class="scenario-block"><div class="scenario-head"><b>演训模拟</b><small>无需影像 · 随机生成紫金山火情</small></div><div v-if="!scenario" class="scenario-empty">点击生成一处在紫金山范围内随机出现的火情，随后开始模拟集群调度推演。</div><div v-else class="scenario-facts"><span>火点 <b>{{ scenario.fireGps.longitude }}°E, {{ scenario.fireGps.latitude }}°N</b></span><span>面积 <b>{{ scenario.areaM2 }} m²</b></span><span>增长率 <b>{{ scenario.growthRate }}/h</b></span><span>人员 <b>{{ scenario.people === 'confirmed' ? '在场' : scenario.people === 'absent' ? '不在场' : '情况不明' }}</b></span><span v-if="scenario.failureRound" class="scenario-drill">⚔ 含单机失能演练（第 {{ scenario.failureRound }} 轮）</span><span v-if="scenario.windShift" class="scenario-drill">🌪 风变演练（第 {{ scenario.windShift.round }} 轮 · {{ scenario.windShift.speed }} m/s）</span></div><div class="demo-scripts"><span>演示脚本</span><button class="outline-btn" :disabled="scenarioBusy || analyzing" title="固定小火：批准→推演→扑灭归档，一条龙速胜" @click="emit('demo-main')">🎬 主场景</button><button class="outline-btn" :disabled="scenarioBusy || analyzing" title="固定中火+第2轮风变跨档：触发重规划→二次审批" @click="emit('demo-perturb')">🌪 扰动场景</button></div><div class="scenario-actions"><button class="outline-btn" :disabled="scenarioBusy || analyzing" @click="emit('generate-scenario')">{{ scenario ? '重新生成火情' : '生成随机火情' }}</button><button v-if="scenario" class="primary scenario-start" :disabled="scenarioBusy || analyzing" @click="emit('start-scenario')"><Bot :size="16" /> 开始模拟</button></div></div></section>
</template>
