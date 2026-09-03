# 森林火灾救援智能体

> 面向森林火灾应急指挥的可运行 MVP：用固定场景数据和确定性规则先跑通“影像输入 → Agent/Skill → Tool → 调度 → 闭环监测”，再逐步替换真实 YOLO、VLM、GIS 与飞控适配器。

## 1. 当前状态

| 模块 | 状态 | 说明 |
|---|---|---|
| Vue 指挥工作台 | ✅ 可运行 | 任务概览、集群、态势、日志和上传交互 |
| FastAPI API | ✅ 可运行 | 健康、分析、上传、任务查询、事件和监测 |
| Agent 分层 | ✅ MVP | Planner、SkillRegistry、ToolRegistry、AnalysisStore |
| 核心规则 Tool | ✅ 演示可运行 | 评估、资源、路线、约束、执行和闭环决策 |
| 视觉输入适配器 | ⚠️ 假数据 | `detect_fire` 根据 fixture/文件名返回观测，不代表 YOLO |
| YOLO / OpenCV | ⏳ 待接入 | 接口已预留 |
| VLM/LLM | ⏳ 待接入 | 只负责解释和补充判断 |
| GIS/在线气象/真实飞控 | ⏳ 待接入 | 不属于当前 MVP |

## 2. 架构

```text
Vue 3 + Vite 工作台
          ↓ HTTP / JSON / multipart
FastAPI API 层
          ↓
AnalysisService（统一应用服务）
          ↓
AnalysisStore（任务状态、结果、事件）
          ↓
SkillOrchestrator
          ↓
火情感知 → 环境研判 → 火情评估 → 资源匹配
          → 无人机调度 → 航线规划 → 任务执行 → 闭环监测
          ↓
ToolRegistry → 29 个原子 Tool
          ↓
规则引擎 / 固定 JSON / 未来模型适配器
```

原则：Skill 负责编排，Tool 负责单一动作，规则代码负责安全关键计算，模型不能直接覆盖等级、资源和约束结果。

## 3. 目录

```text
backend/app/
├─ agents/       # Planner、PlanExecutor
├─ domain/       # Pydantic 契约、内存任务 Store
├─ services/     # AnalysisService
├─ skills/       # SkillRegistry、业务 Skill 链
├─ tools/        # BaseTool、ToolRegistry、规则 Tool
├─ main.py       # FastAPI 入口
└─ pipeline.py   # 兼容的确定性演示管线
frontend/src/
├─ App.vue       # 指挥工作台
├─ style.css     # 工作台视觉样式
└─ main.js
configs/         # 仿真参数
data/            # 场景、机群、库存、视觉观测 fixture
docs/             # 架构、算法、数据字典、演示脚本
 tests/           # 契约和接口测试
```

## 4. 安装与启动

在仓库根目录 `E:/开发/2026ican` 执行。

### 后端

```bash
python -m venv .venv
# Windows PowerShell
.venv\\Scripts\\Activate.ps1
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

如果已有旧进程占用端口，先停止对应 Python/Uvicorn 进程，再启动新实例。

### 前端

另开终端：

```bash
cd frontend
npm install
npm run dev
```

访问：

- 工作台：`http://localhost:5173`
- Swagger：`http://localhost:8000/docs`

## 5. API

### 服务状态

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/project-status
curl http://localhost:8000/api/tools
curl http://localhost:8000/api/skills
```

### JSON 分析

```bash
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"scene_id":"forest-demo-01","image_name":"small-fire.jpg"}'
```

`image_name` 中包含 `small` 时使用小火情 fixture，否则使用默认 fixture。

### 文件上传

```bash
curl -X POST http://localhost:8000/api/analyze/upload \
  -F "file=@fire.jpg;type=image/jpeg" \
  -F "scene_id=forest-demo-01"
```

支持 JPEG、PNG、MP4；最大 200MB；图片会检查文件魔数，并保存到本地 `uploads/`。当前不会把文件送入真实 YOLO。

### 查询任务和事件

```bash
curl http://localhost:8000/api/analyzes
curl http://localhost:8000/api/analyze/<analysis_id>
curl http://localhost:8000/api/analyze/<analysis_id>/events
```

### 闭环监测

```bash
curl -X POST http://localhost:8000/api/monitor/<analysis_id> \
  -H "Content-Type: application/json" \
  -d '{"elapsed_minutes":5,"extinguishing_liters":40}'
```

返回动作包括：`continue`、`resupply`、`reinforce`、`return`、`finish`。

## 6. 演示操作

1. 启动后端和前端。
2. 打开工作台并确认“后端服务在线”。
3. 上传一张合法 JPEG/PNG。
4. 点击“启动智能研判”。
5. 查看分析阶段、数据来源、火情等级、资源需求和无人机任务。
6. 切换“无人机集群”“林区态势”“任务日志”。
7. 点击“执行下一轮监测”。
8. 查看火焰面积、任务状态、下一步动作和新增事件。

## 7. 测试与构建

```bash
# 根目录
python -m py_compile backend/app/main.py backend/app/pipeline.py
pytest -q

# 前端目录
cd frontend
npm run build
```

## 8. 数据与算法说明

- `data/scene.json`：固定场景、风场、火点原点和水源。
- `data/fleet.json`：无人机角色、电量、载荷和状态。
- `data/inventory.json`：水和干粉库存。
- `data/vision_observations.json`：当前视觉假数据 fixture。
- `configs/simulation.json`：风险权重、等级阈值、资源和安全参数。

规则示例：

```text
R_fire = αa + βs + γw + δg
M_required = A_fire × q_base × k_level × k_env × k_safe
A_next = max(0, A_t + G_t - F_t)
```

这些参数仅用于软件演示和链路验证，不代表真实消防作业标准。

## 9. 故障排查

### 页面显示本地演示模式

检查后端是否启动，并确认前端代理指向 `http://127.0.0.1:8000`。

### 端口被占用

Windows 可执行：

```powershell
Get-NetTCPConnection -LocalPort 8000,5173 -State Listen
```

停止确认过的旧进程后再启动。

### 上传返回 415

检查：

- MIME 是否为 `image/jpeg`、`image/png` 或 `video/mp4`；
- 文件内容是否真的匹配扩展名；
- 图片是否包含正确魔数。

### 修改后接口仍返回旧结果

确认旧 Uvicorn/Vite 进程已经停止，并重新启动；不要只依赖热更新状态。

## 10. 已知限制与路线

当前完成的是稳定、可解释的规则演示 MVP。尚未实现：

- 真实 YOLO 权重推理；
- OpenCV 视频抽帧和多帧趋势；
- VLM/LLM 接入；
- 真实 GeoJSON/GIS 和在线气象；
- 多机优化航线和真实能耗模型；
- SQLite 持久化和跨重启历史；
- SSE/WebSocket 实时事件；
- 真实无人机飞控；
- 人群疏散扩展。

推荐后续顺序：

```text
统一结果契约与测试
→ SQLite 任务持久化
→ YOLO 图片适配器
→ 视频抽帧/趋势
→ GIS/环境适配器
→ VLM 解释层
→ SSE 实时事件
→ 更完整的调度优化
```

## 11. 相关文档

- [项目方案](森林火灾救援智能体项目方案.md)
- [系统架构](docs/architecture.md)
- [Agent 分层](docs/agent-architecture.md)
- [算法说明](docs/algorithm.md)
- [数据字典](docs/data-dictionary.md)
- [演示脚本](docs/demo-script.md)
- [任务进度](docs/task-progress.md)
