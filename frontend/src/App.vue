<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  Activity,
  Bell,
  Bot,
  ChevronRight,
  CloudRain,
  Crosshair,
  FileImage,
  Flame,
  Gauge,
  ListFilter,
  Map,
  MapPinned,
  Radio,
  RefreshCw,
  ShieldCheck,
  Upload,
  Wind,
  Zap,
} from 'lucide-vue-next'

const activeTab = ref('command')
const viewTab = ref('overview')
const analyzing = ref(false)
const uploaded = ref(false)
const selectedFile = ref(null)
const previewUrl = ref('')
const fileInput = ref(null)
const progress = ref(0)
const errorMessage = ref('')
const analysisResult = ref(null)
const taskStatus = ref('待命')
const currentStage = ref('等待影像接入')
const monitorResult = ref(null)
const serviceOnline = ref(false)
const projectStatus = ref({ framework: 'checking', demo_pipeline: 'checking', yolo: 'pending', vlm: 'pending', geo_data: 'demo-data' })
const logs = ref([
  '系统已连接 · 等待新的侦察数据',
  '场景「青龙山演示林区」已载入',
  '三架无人机状态同步完成',
])

const scene = {
  id: 'forest-demo-01',
  name: '青龙山演示林区',
  incident: '北坡火情 · 初始研判',
  coordinates: '118.78°E · 32.04°N',
  windSpeed: 6.5,
  windDirection: '西北',
  altitude: 320,
  terrain: '丘陵',
  waterDistance: 800,
}

const drones = ref([
  { id: 'DR-01', label: '侦察蜂', role: 'RECON', battery: 82, status: '执行中', color: 'blue', task: '持续侦察' },
  { id: 'DR-02', label: '灭火蜂', role: 'SUPPRESSION', battery: 75, status: '待命', color: 'orange', task: '主力灭火' },
  { id: 'DR-03', label: '支援蜂', role: 'SUPPORT', battery: 91, status: '待命', color: 'green', task: '水源补给' },
])

const fallbackResult = {
  analysis_id: 'analysis-demo-001',
  fire_assessment: { level: 2, label: 'Ⅱ级 · 中等火情', fire_area_m2: 1800, smoke_area_m2: 4200, confidence: 0.91, spread_direction: '西北' },
  environment: { wind_speed: 6.5, wind_direction: '西北', altitude: 320, terrain: '丘陵', nearest_water_distance_m: 800 },
  dispatch_plan: {
    can_control: true,
    recommended_material: 'water',
    material_amount: 80,
    estimated_minutes: 18,
    tasks: [
      { drone_id: 'DR-01', task: '持续侦察' },
      { drone_id: 'DR-02', task: '主力灭火' },
      { drone_id: 'DR-03', task: '水源补给' },
    ],
  },
  explanation: '当前为中等火情，西北风可能推动火势向西北扩散。建议 DR-02 立即压制火线，DR-03 前往 800m 外水源点补给。',
}

const result = computed(() => analysisResult.value || fallbackResult)
const dataMode = computed(() => result.value.data_mode || '本地演示数据 · 规则引擎')
const metrics = computed(() => [
  { label: '火焰面积', value: formatNumber(result.value.fire_assessment.fire_area_m2), unit: 'm²', change: '+12.4%', tone: 'orange', icon: Flame },
  { label: '烟雾覆盖', value: formatNumber(result.value.fire_assessment.smoke_area_m2), unit: 'm²', change: '+8.1%', tone: 'slate', icon: CloudRain },
  { label: '风速 / 风向', value: result.value.environment.wind_speed, unit: `m/s · ${result.value.environment.wind_direction}`, change: '扩散预警', tone: 'blue', icon: Wind },
  { label: '研判置信度', value: Math.round(result.value.fire_assessment.confidence * 100), unit: '%', change: '高可信', tone: 'green', icon: ShieldCheck },
])

const navItems = [
  { id: 'command', label: '指挥中枢', icon: Crosshair },
  { id: 'fleet', label: '无人机集群', icon: Radio },
  { id: 'map', label: '林区态势', icon: Map },
  { id: 'logs', label: '任务日志', icon: Activity },
]

function formatNumber(value) {
  return new Intl.NumberFormat('zh-CN').format(value)
}

function selectNav(id) {
  activeTab.value = id
  if (id === 'command') viewTab.value = 'overview'
}

function selectView(id) {
  viewTab.value = id
  activeTab.value = id === 'monitor' ? 'map' : id === 'history' ? 'logs' : 'command'
}

function addLog(message) {
  logs.value.unshift(message)
}

async function loadServiceStatus() {
  try {
    const [healthResponse, statusResponse] = await Promise.all([fetch('/api/health'), fetch('/api/project-status')])
    if (!healthResponse.ok || !statusResponse.ok) throw new Error('服务状态检查失败')
    serviceOnline.value = true
    projectStatus.value = await statusResponse.json()
    addLog(`后端服务已连接 · v${(await healthResponse.clone().json()).version}`)
  } catch (error) {
    serviceOnline.value = false
    projectStatus.value = { framework: 'local', demo_pipeline: 'ready', yolo: 'pending', vlm: 'pending', geo_data: 'demo-data' }
    addLog('后端服务未连接 · 使用本地演示结果')
    console.warn(error)
  }
}

function openFilePicker() {
  fileInput.value?.click()
}

function acceptFile(file) {
  errorMessage.value = ''
  if (!file) return
  const allowed = ['image/jpeg', 'image/png', 'video/mp4']
  if (!allowed.includes(file.type)) {
    errorMessage.value = '仅支持 JPG、PNG 或 MP4 文件。'
    return
  }
  if (file.size > 200 * 1024 * 1024) {
    errorMessage.value = '文件大小不能超过 200MB。'
    return
  }
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  selectedFile.value = file
  previewUrl.value = URL.createObjectURL(file)
  uploaded.value = true
  progress.value = 0
  addLog(`已接收新航拍影像 · ${file.name}`)
}

function handleFileChange(event) {
  acceptFile(event.target.files?.[0])
  event.target.value = ''
}

function handleDrop(event) {
  acceptFile(event.dataTransfer.files?.[0])
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function startAnalysis() {
  if (analyzing.value) return
  if (!selectedFile.value) {
    errorMessage.value = '请先选择一张火灾图片或一个航拍视频。'
    addLog('研判未启动 · 尚未接入现场影像')
    return
  }

  analyzing.value = true
  taskStatus.value = '分析中'
  currentStage.value = '正在接入现场影像'
  errorMessage.value = ''
  progress.value = 8
  addLog(`研判任务已启动 · ${selectedFile.value.name}`)

  try {
    const stages = [['正在解析航拍影像…', 24, '正在解析影像'], ['规则演示视觉识别完成 · YOLO 待接入', 48, '视觉识别（演示）'], ['正在融合风场与地形数据…', 72, '环境融合'], ['正在生成集群调度方案…', 90, '调度生成']]
    for (const [message, value, stage] of stages) {
      await sleep(280)
      addLog(message)
      currentStage.value = stage
      progress.value = value
    }

    const formData = new FormData()
    formData.append('file', selectedFile.value)
    formData.append('scene_id', scene.id)
    formData.append('use_vlm', 'false')
    const response = await fetch('/api/analyze/upload', { method: 'POST', body: formData })
    if (!response.ok) throw new Error(`分析服务返回 ${response.status}`)
    const payload = await response.json()
    analysisResult.value = payload.result || payload
    taskStatus.value = '执行中'
    currentStage.value = '调度方案已生成'
    if (analysisResult.value.fleet) {
      drones.value = analysisResult.value.fleet.map((drone) => ({ ...drone, label: drone.role === 'reconnaissance' ? '侦察蜂' : drone.role === 'firefighting' ? '灭火蜂' : '支援蜂', color: drone.role === 'reconnaissance' ? 'blue' : drone.role === 'firefighting' ? 'orange' : 'green', task: analysisResult.value.dispatch_plan.tasks.find((task) => task.drone_id === drone.id)?.task || '待命' }))
    }
    progress.value = 100
    addLog('研判完成 · 建议立即处置')
  } catch (error) {
    analysisResult.value = fallbackResult
    taskStatus.value = '本地演示'
    currentStage.value = '已切换本地演示结果'
    progress.value = 100
    addLog('分析服务暂不可用 · 已切换为本地演示数据')
    errorMessage.value = '分析服务暂不可用，当前展示的是本地演示结果。'
    console.warn(error)
  } finally {
    analyzing.value = false
  }
}

async function runMonitor() {
  if (!analysisResult.value?.analysis_id) return
  try {
    const response = await fetch(`/api/monitor/${analysisResult.value.analysis_id}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ elapsed_minutes: 5, extinguishing_liters: 40 }) })
    if (!response.ok) throw new Error('监测接口不可用')
    monitorResult.value = await response.json()
    addLog(`第 2 轮监测完成 · 下一步：${monitorResult.value.action}`)
    if (monitorResult.value.action === 'finish') taskStatus.value = '已完成'
  } catch (error) {
    errorMessage.value = '监测服务暂不可用。'
    addLog('闭环监测失败 · 保持当前任务状态')
  }
}

function resetAnalysis() {
  analysisResult.value = null
  selectedFile.value = null
  uploaded.value = false
  progress.value = 0
  errorMessage.value = ''
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
  addLog('已清空当前影像 · 等待新的侦察数据')
}

onBeforeUnmount(() => {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})

onMounted(loadServiceStatus)
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><div class="brand-mark"><Flame :size="19" /></div><div><strong>EMBER<span>OS</span></strong><small>RESCUE INTELLIGENCE</small></div></div>
      <div class="scene-card"><div class="eyebrow">CURRENT SCENE</div><div class="scene-name">{{ scene.name }} · 01</div><div class="scene-meta"><span class="live-dot"></span> LIVE SIMULATION <span class="scene-time">09:20:14</span></div></div>
      <nav aria-label="主导航"><button v-for="item in navItems" :key="item.id" :class="{ active: activeTab === item.id }" @click="selectNav(item.id)"><component :is="item.icon" :size="17" /><span>{{ item.label }}</span><b v-if="item.id === 'fleet'">3</b></button></nav>
      <div class="sidebar-foot"><div class="system-status"><span :class="['live-dot', { offline: !serviceOnline }]" /><div><strong>{{ serviceOnline ? '系统运行正常' : '本地演示模式' }}</strong><small>{{ serviceOnline ? '后端服务在线' : '后端服务未连接' }}</small></div></div><div class="operator"><div class="avatar">江</div><div><strong>江月</strong><small>指挥员 · OP-07</small></div><ChevronRight :size="16" /></div></div>
    </aside>

    <main>
      <header><div><div class="breadcrumb">COMMAND CENTER <span>/</span> {{ activeTab.toUpperCase() }}</div><h1>森林火灾救援工作台</h1><p>多源感知 · 智能研判 · 集群调度 · 闭环处置</p></div><div class="header-actions"><button class="icon-btn" title="查看通知"><Bell :size="18" /><i></i></button><div class="utc">UTC+08:00<br><strong>2026.09.02</strong></div></div></header>
      <section class="toolbar"><div class="tab-pills" role="tablist" aria-label="任务视图"><button :class="{ selected: viewTab === 'overview' }" @click="selectView('overview')">任务概览</button><button :class="{ selected: viewTab === 'monitor' }" @click="selectView('monitor')">实时监测</button><button :class="{ selected: viewTab === 'history' }" @click="selectView('history')">历史任务</button></div><div class="toolbar-right"><span class="task-badge">任务状态 · {{ taskStatus }}</span><span class="sync"><span class="live-dot"></span> {{ currentStage }}</span><button class="primary" :disabled="analyzing" @click="startAnalysis"><Bot :size="17" /> {{ analyzing ? '分析中…' : '启动智能研判' }}</button></div></section>
      <div v-if="errorMessage" class="notice" role="status"><Activity :size="16" /><span>{{ errorMessage }}</span><button class="notice-close" title="关闭提示" @click="errorMessage = ''">×</button></div>

      <div v-if="activeTab === 'command'" class="dashboard">
        <section class="hero-panel"><div class="panel-heading"><div><span class="section-kicker">ACTIVE INCIDENT · FF-20260902-001</span><h2>{{ scene.incident }}</h2></div><span class="severity"><span></span>{{ result.fire_assessment.label }}</span></div><div class="map-preview"><div class="map-grid"></div><div class="ridge ridge-a"></div><div class="ridge ridge-b"></div><div class="fire-zone"><span class="pulse"></span><Flame :size="23" fill="currentColor" /><label>火点中心<br><b>{{ scene.coordinates }}</b></label></div><div class="wind-arrow"><Wind :size="20" /><span>{{ result.environment.wind_direction }} {{ result.environment.wind_speed }} m/s</span></div><div class="map-label top">北坡林区 / ZONE A</div><div class="map-label bottom">{{ result.environment.nearest_water_distance_m }}m · 北侧蓄水池</div></div><div class="hero-footer"><div><small>当前处置结论</small><strong>{{ result.dispatch_plan.can_control ? '可控制 · 建议立即出动' : '暂不可控 · 请求增援' }}</strong></div><div class="hero-stat"><small>预计处置时间</small><strong>{{ result.dispatch_plan.estimated_minutes }} <em>MIN</em></strong></div><div class="hero-stat"><small>下次评估</small><strong>05 <em>MIN</em></strong></div></div></section>

        <section class="upload-panel"><div class="panel-heading"><div><span class="section-kicker">INPUT CHANNEL</span><h2>现场影像接入</h2></div><FileImage :size="19" class="muted-icon" /></div><input ref="fileInput" class="visually-hidden" type="file" accept="image/jpeg,image/png,video/mp4" @change="handleFileChange"><div class="dropzone" :class="{ uploaded }" @click="openFilePicker" @dragover.prevent @drop.prevent="handleDrop"><div v-if="previewUrl && selectedFile?.type.startsWith('image/')" class="preview-thumb"><img :src="previewUrl" alt="已选择的火灾影像预览"></div><div v-else class="upload-orb"><Upload :size="22" /></div><strong>{{ uploaded ? '影像已接入' : '拖入航拍图像或视频' }}</strong><span>{{ uploaded ? `${selectedFile.name} · ${(selectedFile.size / 1024 / 1024).toFixed(1)} MB` : '支持 JPG / PNG / MP4 · 最大 200MB' }}</span><button type="button" @click.stop="openFilePicker">{{ uploaded ? '更换文件' : '选择文件' }}</button></div><div class="process"><div class="process-row"><span>分析管线</span><b>{{ progress }}%</b></div><div class="progress"><i :style="{ width: progress + '%' }"></i></div><div class="pipeline"><span :class="{ done: progress >= 24 }">视觉识别</span><ChevronRight :size="13" /><span :class="{ done: progress >= 48 }">环境融合</span><ChevronRight :size="13" /><span :class="{ done: progress >= 72 }">风险评估</span><ChevronRight :size="13" /><span :class="{ done: progress >= 90 }">调度生成</span></div><div class="model-status"><span>YOLO <b>{{ projectStatus.yolo === 'pending' ? '待接入' : '在线' }}</b></span><span>VLM <b>{{ projectStatus.vlm === 'pending' ? '待接入' : '在线' }}</b></span><span>场景数据 <b>固定演示</b></span></div></div><button v-if="uploaded" class="reset-link" @click="resetAnalysis"><RefreshCw :size="13" /> 清空并重新接入</button></section>

        <section class="metrics-grid"><article v-for="metric in metrics" :key="metric.label" class="metric-card"><div class="metric-top"><span>{{ metric.label }}</span><component :is="metric.icon" :size="17" :class="'tone-' + metric.tone" /></div><div class="metric-value">{{ metric.value }} <small>{{ metric.unit }}</small></div><div :class="['metric-change', 'tone-' + metric.tone]">{{ metric.change }}</div></article></section>
        <section class="fleet-panel panel"><div class="panel-heading"><div><span class="section-kicker">FLEET STATUS</span><h2>无人机集群状态</h2></div><button class="text-btn" @click="selectNav('fleet')">查看详情 <ChevronRight :size="14" /></button></div><div class="fleet-list"><div v-for="drone in drones" :key="drone.id" class="drone-row"><div :class="['drone-icon', drone.color]"><Zap :size="17" /></div><div class="drone-name"><strong>{{ drone.id }} <span>{{ drone.label }}</span></strong><small>{{ drone.role }}</small></div><div class="battery"><div class="battery-bar"><i :style="{ width: drone.battery + '%' }"></i></div><span>{{ drone.battery }}%</span></div><span :class="['drone-status', drone.status === '执行中' ? 'active-status' : '']"><i></i>{{ drone.status }}</span></div></div></section>
        <section class="decision-panel panel"><div class="panel-heading"><div><span class="section-kicker">AGENT DECISION</span><h2>调度建议</h2></div><span class="ai-badge"><Bot :size="14" /> {{ dataMode }}</span></div><div class="decision-callout"><div class="decision-icon"><Gauge :size="20" /></div><div><strong>{{ result.dispatch_plan.can_control ? '建议立即启动一级处置响应' : '建议立即请求增援' }}</strong><p>{{ result.explanation }}</p></div></div><div class="task-chips"><span v-for="task in result.dispatch_plan.tasks" :key="task.drone_id"><b>{{ task.drone_id }}</b> {{ task.task }}</span></div><button v-if="analysisResult" class="monitor-btn" @click="runMonitor"><RefreshCw :size="14" /> 执行下一轮监测</button><div v-if="monitorResult" class="monitor-result">监测结果：火焰面积 {{ monitorResult.next_fire_area_m2 }}m² · {{ monitorResult.reason }}</div></section>
        <section class="log-panel panel"><div class="panel-heading"><div><span class="section-kicker">SYSTEM ACTIVITY</span><h2>任务日志</h2></div><span class="log-count">{{ logs.length }} EVENTS</span></div><div class="logs"><div v-for="(log, index) in logs.slice(0, 6)" :key="log + index"><span class="log-time">09:{{ String(20 - index).padStart(2, '0') }}</span><i :class="{ bright: index === 0 }"></i><span>{{ log }}</span></div></div></section>
      </div>

      <section v-else-if="activeTab === 'fleet'" class="detail-view"><div class="detail-heading"><div><span class="section-kicker">FLEET OPERATIONS</span><h2>无人机集群</h2><p>当前集群共有 3 架无人机，状态数据来自演示数据源。</p></div><span class="status-tag"><span class="live-dot"></span> 全部在线</span></div><div class="fleet-detail-grid"><article v-for="drone in drones" :key="drone.id" class="fleet-detail-card"><div :class="['drone-icon large', drone.color]"><Zap :size="20" /></div><div class="fleet-detail-title"><strong>{{ drone.id }}</strong><span>{{ drone.label }}</span></div><div class="fleet-detail-role">{{ drone.role }}</div><div class="detail-battery"><div class="battery-bar"><i :style="{ width: drone.battery + '%' }"></i></div><strong>{{ drone.battery }}%</strong></div><div class="fleet-detail-task"><span>当前任务</span><b>{{ drone.task }}</b></div><button class="outline-btn" @click="addLog(`${drone.id} 状态详情已查看`)"><ListFilter :size="14" /> 查看状态</button></article></div></section>

      <section v-else-if="activeTab === 'map'" class="detail-view map-view"><div class="detail-heading"><div><span class="section-kicker">GEO SITUATION</span><h2>林区态势</h2><p>固定演示场景 · {{ scene.name }} · {{ scene.terrain }}地形 · 海拔 {{ scene.altitude }}m</p></div><span class="status-tag orange"><MapPinned :size="14" /> {{ scene.coordinates }}</span></div><div class="large-map"><div class="map-grid"></div><div class="ridge ridge-a"></div><div class="ridge ridge-b"></div><div class="route-line"></div><div class="map-node fire"><Flame :size="18" fill="currentColor" /><span>火点中心</span></div><div class="map-node water"><MapPinned :size="17" /><span>蓄水池 · {{ scene.waterDistance }}m</span></div><div class="map-node drone one"><Radio :size="15" /><span>DR-01</span></div><div class="map-node drone two"><Radio :size="15" /><span>DR-02</span></div><div class="map-node drone three"><Radio :size="15" /><span>DR-03</span></div><div class="map-compass">N</div><div class="wind-legend"><Wind :size="18" /><span>{{ scene.windDirection }}风 · {{ scene.windSpeed }} m/s</span></div></div></section>

      <section v-else class="detail-view"><div class="detail-heading"><div><span class="section-kicker">SYSTEM ACTIVITY</span><h2>任务日志</h2><p>记录当前演示任务的输入、分析阶段和调度决策。</p></div><span class="status-tag"><Activity :size="14" /> {{ logs.length }} 条记录</span></div><div class="full-logs"><div v-for="(log, index) in logs" :key="log + index"><span class="log-time">09:{{ String(20 - index).padStart(2, '0') }}</span><i :class="{ bright: index === 0 }"></i><span>{{ log }}</span><small>{{ index === 0 ? 'LATEST' : 'EVENT' }}</small></div></div></section>
    </main>
  </div>
</template>
