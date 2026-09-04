# 项目进度

更新时间：2026-09-04

## 已完成

- [x] Vue/Vite 应急指挥工作台与动态八机展示
- [x] FastAPI 健康、分析、上传、任务、审批、重规划、反馈轮次和报告接口
- [x] AnalysisService 统一任务入口与 AnalysisStore 内存状态
- [x] Planner、PlanExecutor、SkillRegistry、ToolRegistry
- [x] 领域契约、枚举校验、旧字段归一化和 `schema_version`
- [x] 2+4+2 资源池：R1–R2、E1–E4、S1–S2；非负库存快照
- [x] 确定性规则 Tool：FLP、SOC、W20/C6、能耗、硬约束、资源缺口、调度评分和离散仿真
- [x] Skill 链：感知、环境、评估、人员分支、候选、过滤、评分、路线、审批、执行、闭环、归档
- [x] 紫金山环境与等高线服务；离线/演示回退和来源标记
- [x] 方案审批闭环：确认、拒绝、调整、终止、资源锁和事件记录
- [x] 5 分钟反馈轮次（内部 1 分钟推进）、重规划触发和报告归档
- [x] 视觉 fixture、上传 MIME/大小/文件魔数校验、契约测试和前端生产构建
- [x] 开发规范与 API 契约：`CONTRIBUTING.md`、`docs/api-contract.md`（2026-09-04）
- [x] 规则 Tool 键名对齐：`calculate_flp_load` 兼容 `k_fuel/k_wind/k_slope` 记法，冻结公式 `B_i = 10×I×K_fuel×K_wind×K_slope` 全因子生效（2026-09-04 修复，此前风/燃料/坡度因子未参与计算）
- [x] 首个方案补齐 `plan_version: 1`，与 `uav-dispatch-v1` 契约一致（2026-09-04）
- [x] 前端演示兜底升级为 2+4+2 正口径：移除 DR-01/02/03、"18 分钟"单点与 3+3+2 旧数据；时间区间改读 `earliest_minutes/latest_minutes`（2026-09-04）
- [x] 前端反馈改用 `POST /api/tasks/{id}/rounds`，不再上送 fleet/inventory 快照（2026-09-04）
- [x] 前端新增：任务报告在线查看、VLM 解释开关、调整约束的出动上限表单；报告下载文件名修正为 `.json`；workbench.css 未闭合花括号修复（2026-09-04）
- [x] 测试补齐：规则算例（tests/test_rules.py）、YOLO/VLM 适配协议（tests/test_adapters.py）、六场景 API 级验收（tests/test_scenarios.py）（2026-09-04）
- [x] 路由层按域拆分：`routes/task_routes.py`（开发者 A）与 `routes/environment_routes.py`（开发者 B），`main.py` 仅做装配；双人平台分工与文件所有权表见 CONTRIBUTING.md 第 3、4 节（2026-09-04）
- [x] 修改追踪清单建立：[docs/修改追踪清单.md](修改追踪清单.md)，已回填 7 项完成、登记待办 A-1~A-7 / B-1~B-8 / J-1~J-2 / E-1~E-3（2026-09-04）

## 当前为演示实现

- [ ] `AnalysisStore` 仅存在内存，重启后任务、锁、事件和报告索引丢失。
- [ ] 规则参数和 FLP 是团队仿真设定，不代表专业消防标准；面积仅作为网格展示辅助。
- [ ] 路线仍以演示距离/地形数据为主，不包含生产级障碍避让和 A* 全量优化。
- [ ] 任务执行模拟状态、SOC、药剂与 FLP 变化，不连接真实飞控。
- [ ] 视觉 fixture 尚未替换为真实 YOLO/PWM-YOLO 权重；VLM 仅保留适配边界。
- [ ] 环境真实坐标查询可能因依赖或网络失败回退，必须保留 `mode` 和来源说明。

## 交付验收口径

- [x] 八架资源动态返回，过滤故障/低 SOC/超载设备，库存不为负。
- [x] 方案生成与执行分离，未审批方案不能执行；状态变化均有事件。
- [x] 有人、无人、unknown 三分支及支援资源保留规则。
- [x] 每 5 分钟轮次对比 FLP、SOC、药剂、库存、环境和 UAV 状态。
- [x] 关键事件触发重规划，并保存方案版本与资源缺口。
- [x] 完成后可查询报告，保留输入、审批、轮次、事件、消耗和结论。
- [x] 2026-09-04 自动化门禁全绿：`pytest -q` 33 passed、`python -m py_compile`、`cd frontend && npm run build`；六场景已由 tests/test_scenarios.py 在 API 层覆盖。
- [ ] 浏览器端六场景人工验收（演示录制前执行一次）。

## 后续接入

- [ ] YOLO/PWM-YOLO 权重与真实图片检测
- [ ] OpenCV 视频抽帧和多帧趋势
- [ ] VLM 解释适配器
- [ ] 更完整 GeoJSON/GIS、在线气象和实时水源
- [ ] SQLite 持久化、SSE/WebSocket 和认证
- [ ] 多机优化航线、真实能耗、飞控与人群疏散扩展

## 统一冻结口径

```text
2+4+2 资源池；FLP 火情负荷；W20/C6 药剂；SOC 按分钟计算；5 分钟反馈；
先硬约束后评分；用户确认后执行；紫金山环境来源可追溯；任务最终报告归档。
```
