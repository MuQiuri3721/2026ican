# 项目检查记录

更新时间：2026-09-03

## 已完成

- [x] Vue/Vite 应急指挥工作台
- [x] FastAPI 健康、分析、上传、任务查询、事件和监测接口
- [x] AnalysisService 统一分析入口
- [x] AnalysisStore 内存任务状态和事件
- [x] Planner、PlanExecutor、SkillRegistry、ToolRegistry
- [x] 29 个 Tool 契约；规则、资源、路线、执行和闭环 Tool 可运行
- [x] 10 个 Skill 注册；核心 Skill 链可运行
- [x] 视觉观测 fixture 和小火情 fixture
- [x] 上传 MIME、大小和文件魔数校验
- [x] 契约测试和前端生产构建
- [x] 根 README、前后端 README 和基础文档

## 当前为演示骨架

- [ ] `AnalysisStore` 只存在内存，重启后任务丢失。
- [ ] 规则参数为项目假设，不代表专业消防标准。
- [ ] 路线为直线演示，不包含真实障碍和 A*。
- [ ] 任务执行只模拟状态和面积变化，不连接飞控。
- [ ] 前端历史页目前主要复用日志视图，待接入任务列表展示。

## 待接入

- [ ] YOLO 权重和真实图片检测。
- [ ] OpenCV 视频抽帧和多帧趋势。
- [ ] VLM/LLM 解释适配器。
- [ ] GeoJSON/GIS、在线气象和实时水源。
- [ ] SQLite 持久化、SSE/WebSocket。
- [ ] 多机优化调度、真实能耗和飞控。
- [ ] 人群疏散扩展。
