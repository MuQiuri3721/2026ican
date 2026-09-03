# Agent 分层说明

本项目采用知识库中总结的：

```text
高层目标 → Plan → Step → Skill → Tool → 结构化结果
```

## 分层职责

- `domain/`：Pydantic 输入输出契约、任务状态和事件。
- `services/analysis_service.py`：统一分析用例，所有入口共享它。
- `agents/planner.py`：固定模板规划步骤，校验依赖。
- `agents/plan_executor.py`：按依赖拓扑执行，同层可并行，失败可重试。
- `skills/`：把多个 Tool 组合成火情感知、环境研判、资源匹配、调度和闭环能力。
- `tools/`：原子动作，统一通过 `BaseTool.execute()` 返回 `ok/tool/source/data/error`。

## 调用关系

```text
POST /api/analyze 或 /api/analyze/upload
        ↓
AnalysisService
        ↓
SkillOrchestrator
        ↓
fire_perception → environment_assessment → fire_assessment
        → resource_matching → drone_dispatch → route_planning
        → task_execution → closed_loop_monitoring
        ↓
AnalysisStore 保存任务、阶段、结果和事件
```

## 解耦替换点

```text
detect_fire       → YOLO Adapter
extract_frames    → OpenCV Adapter
analyze_with_vlm  → Kimi/Qwen Adapter
get_environment   → GeoJSON/GIS Adapter
AnalysisStore     → SQLite Adapter
事件通知           → SSE/WebSocket
```

规则和安全约束不能由模型直接覆盖。模型未来只负责解释、补充判断或提出计划，后端必须校验计划和数值。
