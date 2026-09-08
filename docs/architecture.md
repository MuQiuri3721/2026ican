# 系统架构

## 运行时链路

```text
Vue 指挥工作台
   ↓ JSON / multipart
FastAPI API
   ↓
AnalysisService（任务生命周期与统一用例）
   ├─ AnalysisStore：任务、方案版本、审批、轮次、事件、资源锁
   ├─ Environment/Terrain Service：紫金山环境、道路、水源、等高线
   └─ SkillOrchestrator
        ↓
火情感知 → 环境研判 → 火情评估 → 人员分支
→ 候选生成 → 硬约束过滤 → 调度评分 → 航线规划
→ 方案审批 → 任务执行模拟 → 闭环监测 → 报告归档
        ↓
ToolRegistry → 确定性规则 Tool / JSON 数据 / 未来适配器
```

## 代码边界

- API 只负责协议、输入校验和 HTTP 错误映射。
- Service 负责任务状态、方案版本、审批、资源锁、反馈轮次和报告。
- Skill 负责业务步骤编排与结构化上下文传递。
- Tool 负责单一查询或计算；FLP、SOC、药剂需求、可行性和评分必须由确定性 Tool 产出。
- 环境服务负责紫金山固定场景及 `offline/demo-fallback` 来源标记。
- Adapter 是未来 YOLO/VLM、GIS、气象、数据库和飞控的替换点。

## 状态与审批

```text
queued → running → awaiting_confirmation → approved → executing
                                      ↘ reject/adjust
executing → replanning → awaiting_confirmation → executing → completed
任意非终态 → terminated；任意状态 → failed
```

方案生成不等于执行。只有用户确认当前方案后才能锁定资源并进入执行；每次审批、重规划、轮次和状态变化都写入事件。反馈按 1 分钟内部模拟、5 分钟对外展示，关键事件可提前重规划。任务结束生成报告，保留输入、方案版本、审批记录、轮次、消耗和结论。

## 资源与数据一致性

初始虚拟资源为 R1–R2、E1–E6、S1–S4 十二架独立 UAV（S3/S4 为 multi_role 多用途支援机）。先过滤 `fault`、低健康度、低 SOC、超载和药剂不兼容记录，再评分；支援机负责通信、人员分支指引、物资/电池运输，不描述空中充电或运送人员。状态、资源锁和库存扣减在同一锁范围内更新。

当前 Store 为内存实现，适合演示；真实部署应替换为持久化存储并增加认证和实时事件，不改变 API/Skill/Tool 边界。
