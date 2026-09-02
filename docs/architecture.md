# 系统架构

```text
Vue 工作台
  ├─ 影像接入与预览
  ├─ 阶段/任务状态
  ├─ 态势与集群视图
  └─ 闭环监测操作
          ↓ HTTP
FastAPI API
  ├─ analyze / analyze/upload
  ├─ monitor/{analysis_id}
  └─ health / project-status
          ↓
规则演示 Pipeline
  ├─ 场景、机群、库存读取
  ├─ 火情风险评估
  ├─ 资源需求计算
  ├─ 调度约束校验
  └─ 面积闭环更新
```

YOLO、VLM、GIS 和真实飞控作为后续适配器接入，不改变 API 结果契约。
