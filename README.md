# 森林火灾救援智能体

> 面向紫金山固定森林区域的可运行森林火情研判与无人机资源调度 MVP。系统以“感知—研判—调度—审批—执行模拟—反馈重规划—报告归档”为主线，使用确定性规则先跑通全链路，再逐步替换真实 YOLO、VLM、GIS 与飞控适配器。

## 当前状态

| 模块 | 状态 | 说明 |
|---|---|---|
| Vue 指挥工作台 | 可运行 | 任务概览、动态机群、态势、日志、上传与闭环交互 |
| FastAPI API | 可运行 | 分析、上传、任务计划、审批、重规划、轮次、报告和兼容监测 |
| Agent/Skill/Tool 分层 | MVP | Planner、PlanExecutor、SkillRegistry、ToolRegistry |
| 规则计算 | 演示可运行 | FLP、SOC、W20/C6、硬约束、资源缺口、调度评分和离散仿真 |
| 资源池 | 已扩编 | 2+6+4 共 12 架：R1–R2 侦察、E1–E6 灭火、S1–S4 支援（S3/S4 多用途可参与灭火） |
| 环境 | 已接入 | 紫金山地形、风场、水源、道路和等高线；支持离线/演示回退 |
| 审批与闭环 | 已接入 | 确认/拒绝/调整/终止、资源锁、5 分钟反馈与重规划 |
| 报告 | 已接入 | 保留输入、方案版本、审批、轮次、事件、消耗和结论；含输入文件 hash 溯源 |
| 多 Agent 协作 | 已接入 | agentkit + 六角色（指挥/侦察/压制/支援/研判/审批）黑板消息流，GLM 参与研判与叙述、带确定性降级 |
| 演练与闭环 | 已接入 | 失能自动补位、风变跨档重规划（再审批）、执行期就地取水、结案回收（机群返航+RECOVERY） |
| 视觉理解 | 已接入 | VLM=glm-4.6v-flash 真实接入（图片/多图/视频自动抽帧，含契约守卫与限流降级）；YOLO=接收面就绪待交付 |
| 指挥员问答 | 已接入 | ChatPanel 接地任务实时数据（库存/方案），数字审计防编造 |
| 三维与广播 | 已接入 | 真实 DEM 三维地形；疏散路线 Edge TTS 语音广播 |
| 测试资产 | 已接入 | pytest 125 项；E2E R1-R16+六场景+边界扫描 44 项+API 全功能 38 项 |
| 真实飞控/GIS 导航 | 仿真 | 任务执行为仿真状态机，不连接真实设备与生产导航 |

## 业务链路

```text
地点/图片输入
  → 火情感知 → 紫金山环境研判 → FLP 火情评估 → 有人/无人分支
  → 候选生成 → 硬约束过滤 → 调度评分 → 方案待确认
  → 用户审批 → 执行模拟 → 5 分钟反馈 → 重规划或完成
  → 报告归档
```

智能体负责组织 Skill、调用 Tool、处理分支和解释；规则 Tool 负责火情等级/FLP、资源需求、SOC、载荷、药剂兼容、路线可行性、无人机数量、灭火效果和时间区间。模型不得直接覆盖安全关键数字。

## 统一演示口径

- **资源**：2+6+4 共 12 架独立 UAV（2026-09-08 扩编，原 2+4+2）；系统根据火情和硬约束动态出动。R 负责监测，E 负责灭火，S 负责通信、人员指引、物资/电池运输和后备保障，其中多用途支援机 S3/S4 可携带水剂模块直接参与灭火。
- **火情**：地图可以显示 100 m² 网格，内部使用 FLP 表示处置负荷，不采用旧的固定平方米/小时或面积/升水能力。
- **药剂**：W20 水剂用于一般植被火；C6 CO₂ 只用于局部设备、电气热点或小范围复燃点，同一架次不混装。
- **电量与时间**：SOC 按 1 分钟内部步长计算，预计返航 SOC 必须不低于 25%；界面每 5 分钟展示反馈轮次。时间由仿真输出区间或资源缺口，不使用旧的“18 分钟”单点结论。
- **审批**：生成方案不等于执行；必须确认后锁定资源并进入执行。拒绝、调整、终止、重规划和轮次均记录事件。
- **环境与归档**：优先使用紫金山固定场景；真实坐标依赖缺失或网络失败时返回并标记 `offline/demo-fallback`。任务结束生成可追溯报告。

## 目录

```text
backend/app/
├─ agents/       # Planner、PlanExecutor
├─ domain/       # Pydantic 契约、任务状态、AnalysisStore
├─ services/     # AnalysisService、环境与报告服务
├─ skills/       # SkillRegistry、业务 Skill 链
├─ tools/        # BaseTool、ToolRegistry、规则 Tool
├─ main.py       # FastAPI 入口
└─ pipeline.py   # 兼容的确定性演示管线
frontend/src/     # Vue 工作台
configs/          # 仿真参数
data/             # 场景、2+6+4 机群、库存和视觉 fixture
docs/             # 需求、架构、算法、数据、演示和进度
data/reports/     # 任务报告输出（运行时生成，git 忽略）
tests/            # 契约和接口测试
```

## 安装与启动

后端：

```bash
python -m venv .venv
# Windows PowerShell
.venv\\Scripts\\Activate.ps1
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

前端另开终端：

```bash
cd frontend
npm install
npm run dev
```

访问工作台 `http://localhost:5173`，Swagger `http://localhost:8000/docs`。

## 主要 API

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/fleet
curl http://localhost:8000/api/inventory
curl http://localhost:8000/api/skills

curl -X POST http://localhost:8000/api/analyze \\
  -H "Content-Type: application/json" \\
  -d '{"scene_id":"forest-demo-01","image_name":"small-fire.jpg","environment_mode":"offline"}'
```

任务闭环接口：

```text
GET  /api/tasks/{task_id}/plan
POST /api/tasks/{task_id}/approval       approve/reject/adjust/terminate
POST /api/tasks/{task_id}/replan
POST /api/tasks/{task_id}/rounds
GET  /api/tasks/{task_id}/report
GET  /api/tasks/{task_id}/events/stream  SSE 事件实时推送
```

旧的 `POST /api/monitor/{analysis_id}` 继续保留；其 `extinguishing_liters` 仅在入口转换为 W20 输入，避免旧面积规则污染新领域模型。上传支持 JPEG、PNG、MP4，当前文件不会送入真实 YOLO。

## 验证

```bash
pytest -q
python -m py_compile backend/app/main.py backend/app/pipeline.py
cd frontend && npm run build
```

## 已知限制与后续

任务、事件和资源锁已通过 SQLite 写穿持久化（`data/analysis_store.db`，删除该文件即重置演示状态）；规则参数和 FLP 为团队仿真设定，不代表专业消防标准；路线为演示模型，不是生产级障碍避让；执行不连接飞控；视觉默认 fixture。后续按优先级接入真实 YOLO/PWM-YOLO、视频抽帧、VLM、在线 GIS/气象、WebSocket 双向控制、真实能耗与飞控。

## 相关文档

- [开发规范](CONTRIBUTING.md)
- [API 契约](docs/api-contract.md)
- [修改追踪清单](docs/修改追踪清单.md)
- [需求摘要](docs/requirements.md)
- [系统架构](docs/architecture.md)
- [Agent 分层](docs/agent-architecture.md)
- [算法说明](docs/algorithm.md)
- [数据字典](docs/data-dictionary.md)
- [演示脚本](docs/demo-script.md)
- [任务进度](docs/task-progress.md)
- [项目方案](森林火灾救援智能体项目方案.md)
