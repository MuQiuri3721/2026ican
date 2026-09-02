# 森林火灾救援智能体

## 当前版本

这是一个面向森林火灾应急指挥的可运行 MVP，包含 Vue 工作台、FastAPI 规则演示管线、固定场景数据和闭环监测模拟。

## 启动

```bash
cd frontend
npm install
npm run dev
```

另开终端：

```bash
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

访问 `http://localhost:5173`，API 文档位于 `http://localhost:8000/docs`。

## 当前能力状态

| 能力 | 状态 |
|---|---|
| Vue 工作台、上传预览、导航详情 | 已完成 |
| FastAPI 健康检查与项目状态 | 已完成 |
| 固定场景/机群/物资数据读取 | 已完成 |
| 规则火情评估与资源调度 | 演示版已完成 |
| Multipart 文件上传 | 演示版已完成，仅保存内存元数据 |
| 下一轮监测与面积更新 | 演示版已完成 |
| YOLO 火点识别 | 待接入 |
| VLM/LLM 解释 | 待接入 |
| 真实 GIS、飞控和传感器 | 未开始 |

## API

- `GET /api/health`
- `GET /api/project-status`
- `POST /api/analyze`：JSON 规则演示分析
- `POST /api/analyze/upload`：multipart 图片/视频分析
- `POST /api/monitor/{analysis_id}`：闭环监测模拟

## 重要说明

当前火焰面积、烟雾面积和增长率属于演示输入，规则计算不代表真实消防作业标准。YOLO、VLM 和无人机控制均未宣称已实现。
