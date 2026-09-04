# 后端

Forest Fire Rescue Agent 的 FastAPI 服务层，面向紫金山固定森林演示场景。

## 启动

从仓库根目录执行：

```bash
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

Swagger：`http://localhost:8000/docs`

## 分层与链路

```text
HTTP API → routes/task_routes.py（任务/平台路由，开发者 A）
         → routes/environment_routes.py（环境/等高线路由，开发者 B）
         → AnalysisService → SkillOrchestrator → SkillRegistry → ToolRegistry → Tools
                         └→ AnalysisStore（任务、方案、审批、轮次、事件、资源锁）
```

核心链路为：

```text
火情感知 → 环境研判 → 火情评估 → 有人/无人分支 → 候选与硬约束
→ 调度评分 → 方案审批 → 任务执行模拟 → 5 分钟反馈重规划 → 报告归档
```

所有安全关键数值由确定性规则 Tool 计算。智能体只负责组织 Skill、调用 Tool 和解释结果，不能直接覆盖 FLP、SOC、药剂需求、无人机数量或完成时间。

## 当前演示口径

- 初始资源池固定为 2+4+2：R1–R2 侦察、E1–E4 灭火、S1–S2 支援；根据约束动态出动，不是固定三架。
- 火情负荷使用 FLP；地图可展示 100 m² 网格，但不以“平方米/小时”作为灭火能力。
- 药剂模块为 W20 水剂或 C6 CO₂：植被火默认 W20，C6 仅用于局部设备/电气热点。
- SOC 按 1 分钟内部步长折算，预计返航 SOC 低于 25% 时方案不可执行；界面按 5 分钟反馈轮次展示。
- 任务生成后必须经过 `approve` 才能执行；拒绝、调整、终止和重规划均写入事件。
- 环境优先使用紫金山固定场景的地形、风场、水源、道路和等高线数据；离线或依赖不可用时标注 `offline/demo-fallback`，不阻塞服务。
- 任务结束后生成可追溯报告，保留输入、方案版本、审批、反馈轮次、资源消耗和结论。

## 主要接口

```text
GET  /api/fleet
GET  /api/inventory
GET  /api/tasks/{task_id}/plan
POST /api/tasks/{task_id}/approval       approve/reject/adjust/terminate
POST /api/tasks/{task_id}/replan
POST /api/tasks/{task_id}/rounds
GET  /api/tasks/{task_id}/report
POST /api/monitor/{analysis_id}          旧接口兼容，旧升水量转换为 W20 输入
```

AnalysisStore 使用 SQLite 写穿持久化（`data/analysis_store.db`，git 忽略），重启后任务、方案版本、事件和资源锁可恢复；规则快照和视觉仍为演示 fixture。真实 YOLO/VLM、生产级 GIS、飞控属于后续适配能力。
