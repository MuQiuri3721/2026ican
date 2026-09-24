<script setup>
// 火情监测·影像主舞台（2026-09-23 设计稿参考图）：航拍画面为页面主角，
// YOLO 检测框叠加、帧序列缩略图、上传/采集/翻帧控制收进舞台本身。
// 文件接收与研判编排仍在 App（与 UploadPanel 同一契约，本组件只发意图）。
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Camera, ChevronLeft, ChevronRight, FileVideo, ImagePlus, Radio, RefreshCw } from 'lucide-vue-next'

const props = defineProps({
  previewUrl: { type: String, default: '' },
  frames: { type: Array, default: () => [] }, // [{url,label,time}] 末位为当前帧
  boxes: { type: Object, default: null }, // {boxes, model, fire, smoke}
  analyzing: { type: Boolean, default: false },
  progress: { type: Number, default: 0 },
  uploaded: { type: Boolean, default: false },
  fileName: { type: String, default: '' },
  capturedAt: { type: String, default: '' },
  quality: { type: String, default: '良好' },
  uavLabel: { type: String, default: 'R1' },
})
const showBoxes = defineModel('showBoxes', { type: Boolean, default: true })
const activeIndex = defineModel('activeIndex', { type: Number, default: 0 })
const emit = defineEmits(['files', 'capture', 'reset'])

const imageInput = ref(null)
const videoInput = ref(null)

// 翻帧边界：帧序列变化时钳回末位（当前帧）
watch(() => props.frames.length, (len) => { activeIndex.value = Math.max(0, len - 1) })
const canPrev = computed(() => activeIndex.value > 0)
const canNext = computed(() => activeIndex.value < props.frames.length - 1)
const activeFrame = computed(() => props.frames[activeIndex.value] || null)
const isLatest = computed(() => activeIndex.value === props.frames.length - 1)
const displayUrl = computed(() => activeFrame.value?.url || props.previewUrl)
const stageBoxes = computed(() => (isLatest.value && showBoxes.value && props.boxes?.boxes?.length ? props.boxes.boxes : []))

// —— 现场采集：USB 相机/网络视频流抓一帧 → 走 App 统一研判链路 ——
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

function onDrop(event) {
  emit('files', event.dataTransfer.files)
}
</script>

<template>
  <section class="fm-stage" aria-label="现场影像">
    <div class="fm-stage-head">
      <div class="fm-stage-src">
        <span class="fm-live-chip" :class="{ demo: !uploaded }"><i></i>{{ uploaded ? '实时' : '待接入' }}</span>
        <span v-if="uploaded" class="fm-src-item">状态 <b>影像已接入</b></span>
        <span class="fm-src-item">侦察机 <b>{{ uavLabel }}</b></span>
        <span v-if="capturedAt" class="fm-src-item">拍摄 <b>{{ capturedAt }}</b></span>
        <span class="fm-src-item">画质 <b>{{ quality }}</b></span>
      </div>
      <div class="ev-toggle" role="group" aria-label="原图与检测结果切换">
        <button :class="['legend-item', { on: !showBoxes }]" :aria-pressed="!showBoxes" @click="showBoxes = false">原图</button>
        <button :class="['legend-item', { on: showBoxes }]" :aria-pressed="showBoxes" @click="showBoxes = true">检测结果</button>
      </div>
    </div>

    <div class="fm-stage-body" @dragover.prevent @drop.prevent="onDrop">
      <template v-if="cameraOn">
        <video ref="videoRef" autoplay playsinline muted></video>
        <div class="fm-camera-actions">
          <button class="primary" @click="captureFrame"><Camera :size="15" /> 抓帧并研判</button>
          <button class="outline-btn" @click="stopCamera">取消</button>
        </div>
        <p v-if="cameraError" class="fm-camera-error">{{ cameraError }}</p>
      </template>
      <template v-else-if="displayUrl">
        <img :src="displayUrl" :alt="activeFrame?.label || fileName || '侦察回传画面'">
        <div v-for="(box, i) in stageBoxes" :key="i" :class="['ew-box', box.cls === '火焰' ? 'ew-fire' : 'ew-smoke']" :style="{ left: box.left, top: box.top, width: box.width, height: box.height }">
          <em>{{ box.cls }} {{ box.conf }}%</em>
        </div>
        <div v-if="frames.length > 1" class="fm-frame-pos">{{ activeIndex + 1 }} / {{ frames.length }} · {{ activeFrame?.label }}</div>
      </template>
      <template v-else>
        <div class="fm-stage-empty">
          <div class="fm-empty-orb"><ImagePlus :size="26" /></div>
          <b>等待现场影像接入</b>
          <span>拖入航拍图像 / 视频，或使用下方按钮接入 · 支持多选图片组成序列</span>
          <div class="fm-empty-actions">
            <button class="primary" @click="imageInput?.click()"><ImagePlus :size="15" /> 图片上传</button>
            <button class="outline-btn" @click="videoInput?.click()"><FileVideo :size="15" /> 视频上传</button>
            <button class="outline-btn" @click="openCamera"><Camera :size="15" /> 摄像头采集</button>
          </div>
          <p v-if="cameraError" class="fm-camera-error">{{ cameraError }}</p>
        </div>
      </template>

      <div v-if="analyzing" class="fm-analyzing" role="status">
        <div class="fm-analyzing-row"><span>分析管线运行中 · 视觉识别 → 环境融合 → 风险评估 → 调度生成</span><b>{{ progress }}%</b></div>
        <div class="fm-progress"><i :style="{ width: progress + '%' }"></i></div>
      </div>
    </div>

    <div class="fm-stage-bar">
      <button class="fm-nav-btn" :disabled="!canPrev" :aria-label="上一帧" @click="activeIndex -= 1"><ChevronLeft :size="15" /></button>
      <div class="fm-thumbs" role="listbox" aria-label="帧序列缩略图">
        <button v-for="(frame, i) in frames" :key="frame.url + i" :class="['fm-thumb', { active: i === activeIndex, latest: i === frames.length - 1 }]" :title="frame.label" role="option" :aria-selected="i === activeIndex" @click="activeIndex = i">
          <img :src="frame.url" :alt="frame.label">
          <span v-if="frames.length > 1" class="fm-thumb-time">{{ frame.time || `帧${i + 1}` }}</span>
        </button>
        <div v-if="!frames.length" class="fm-thumbs-empty">帧序列缩略图 · 接入后显示（多选图片 / 视频抽帧）</div>
      </div>
      <button class="fm-nav-btn" :disabled="!canNext" :aria-label="下一帧" @click="activeIndex += 1"><ChevronRight :size="15" /></button>
      <div class="fm-stage-actions">
        <input ref="imageInput" class="visually-hidden" type="file" accept="image/jpeg,image/png" multiple @change="(e) => { emit('files', e.target.files); e.target.value = '' }">
        <input ref="videoInput" class="visually-hidden" type="file" accept="video/mp4" @change="(e) => { emit('files', e.target.files); e.target.value = '' }">
        <button class="fm-ctl-btn" title="上传航拍图片（可多选组成序列）" @click="imageInput?.click()"><ImagePlus :size="14" /> 图片上传</button>
        <button class="fm-ctl-btn" title="上传航拍视频（自动抽帧）" @click="videoInput?.click()"><FileVideo :size="14" /> 视频上传</button>
        <button class="fm-ctl-btn" title="USB 相机/视频流抓帧" @click="openCamera"><Camera :size="14" /> 摄像头采集</button>
        <button v-if="uploaded" class="fm-ctl-btn" title="清空并重新接入" @click="emit('reset')"><RefreshCw :size="14" /> 重接</button>
      </div>
    </div>

    <p v-if="boxes && isLatest" class="fm-stage-note"><Radio :size="12" /> {{ boxes.model }} 真实检测 · {{ boxes.boxes.length }} 框（火焰 {{ boxes.fire }} / 烟雾 {{ boxes.smoke }}）</p>
    <p v-else-if="uploaded && !boxes" class="fm-stage-note muted"><Radio :size="12" /> 检测框随研判生成 · YOLO 视觉观察仅陈述所见，FLP 与安全数值由规则引擎计算</p>
  </section>
</template>
