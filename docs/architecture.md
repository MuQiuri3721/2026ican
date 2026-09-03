# 系统架构

## 运行时链路

```text
Vue 工作台
   ↓ JSON / multipart
FastAPI API
   ↓
AnalysisService
   ├─ AnalysisStore：任务、状态、事件
   └─ SkillOrchestrator：核心业务链
         ↓
火情感知 → 环境研判 → 火情评估 → 资源匹配
         → 无人机调度 → 航线规划 → 任务执行 → 闭环监测
         ↓
ToolRegistry → 领域 Tool → JSON 数据 / 规则 / 适配器
```

## 代码边界

- API 只负责协议、输入边界和 HTTP 错误。
- Service 负责用例和任务生命周期。
- Skill 负责业务步骤编排和上下文传递。
- Tool 负责单一查询或计算动作。
- Rule Tool 负责等级、资源、电量和计划安全校验。
- Adapter 是未来 YOLO、VLM、GIS、气象和飞控的替换点。

## 当前与未来

当前使用内存 Store 和固定 JSON，适合演示和接口联调。生产化时优先替换 Store 为 SQLite，再增加真实模型、SSE 和认证，不改变 API/Skill/Tool 的边界。
