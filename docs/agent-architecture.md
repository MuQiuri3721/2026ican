# Agent 分层说明

## 总体模型

```text
高层目标 → Plan → Step → Skill → Tool → 结构化结果
```

- `domain/`：Pydantic 契约、领域枚举、任务状态和事件。
- `services/analysis_service.py`：统一任务用例，串联计划、审批、轮次和报告。
- `agents/`：生成并执行有依赖的固定计划，不让模型绕过约束。
- `skills/`：组合 Tool，传递结构化上下文，处理有人/无人/unknown 分支。
- `tools/`：单一、可复算的动作，统一返回 `ok/tool/source/data/error`。
- `AnalysisStore`：内存保存任务、方案版本、审批、反馈、锁和事件。

## 核心 Skill 链

```text
fire_perception
→ environment_assessment
→ fire_assessment
→ people_assessment
→ candidate_generation
→ constraint_filtering
→ dispatch_scoring
→ route_planning
→ approval_preparation
→ task_execution
→ closed_loop_monitoring
→ report_archiving
```

环境节点读取紫金山场景的风、坡度、地形、水源、道路和来源标签。资源节点读取 2+4+2 的八架独立快照和库存。规则节点计算 FLP、SOC_need、W20/C6 兼容性、资源缺口和时间区间；先硬约束，再离散仿真和评分。智能体只负责调用顺序、异常分支和解释数字来源。

## 审批与闭环

方案必须进入 `awaiting_confirmation`，用户可 `approve`、`reject`、`adjust` 或 `terminate`。确认后才锁定资源和执行；调整会生成新方案版本，拒绝释放锁。每 5 分钟形成反馈轮次，比较 FLP、SOC、药剂、库存、环境与 UAV 状态，遇到关键事件触发重规划；达到控制目标后由报告 Skill 归档全链路记录。

## 可替换适配器

```text
detect_fire       → YOLO/PWM-YOLO Adapter
extract_frames    → OpenCV Adapter
analyze_with_vlm  → VLM Adapter
get_environment   → GIS/GeoJSON Adapter
AnalysisStore     → SQLite Adapter
事件通知           → SSE/WebSocket
```

模型不能直接覆盖火情等级、无人机数量、耗电、灭火效果、资源缺口或完成时间。`offline/demo-fallback` 仅是明确标注的演示降级路径。
