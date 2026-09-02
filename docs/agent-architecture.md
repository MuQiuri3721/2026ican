# Agent 分层说明

本项目参考知识库中的 Agent 实践，采用“入口 → Skill → Plan → Tool → 结构化结果”的解耦流程。

## 分层

- `agents/planner.py`：根据高层目标生成步骤计划，并校验重复 ID、自依赖和不存在的依赖。
- `skills/fire_analysis.py`：面向业务目标编排步骤，是可替换的 Skill 层。
- `tools/registry.py`：按名称注册、查询和执行原子 Tool。
- `tools/environment.py`：环境、机群和库存查询 Tool。
- `pipeline.py`：确定性规则引擎，负责安全关键的数值计算，不交给模型自由生成。
- `domain/models.py`：计划步骤、状态和结果领域模型。

## 调用关系

```text
POST /api/skills/fire_analysis/run
        ↓
SkillRegistry
        ↓
FireAnalysisSkill
        ├─ AnalysisPlanner.create_plan
        ├─ ToolRegistry.execute(get_environment)
        └─ run_demo_analysis
                ↓
          结构化 JSON
```

## API

- `GET /api/tools`：查看已注册 Tool
- `GET /api/skills`：查看已注册 Skill
- `POST /api/skills/{skill_name}/run`：执行指定 Skill

## 设计原则

1. Tool 只做一个明确动作，输入输出清晰。
2. Skill 只编排业务流程，不把具体数据读取写死在 API 层。
3. Planner 只负责计划，不直接执行危险动作。
4. 规则引擎负责等级、资源、电量和安全约束。
5. 未来接入 VLM 时，只替换 `vision` 步骤的实现，不改变 API 和调度规则。
6. 未来接入真实环境数据时，只替换环境 Tool，不修改 Skill 调用方。
7. 所有模型输出都要经过后端校验，不能直接覆盖安全关键结果。

## 后续替换点

```text
vision Tool       → YOLO Adapter
explanation Tool  → Kimi/Qwen VLM Adapter
environment Tool  → GeoJSON/GIS Adapter
Planner           → LLM Planner + PlanValidator
任务存储           → SQLite/数据库
事件通知           → SSE/WebSocket
```
