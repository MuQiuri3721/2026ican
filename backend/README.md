# 后端

Forest Fire Rescue Agent 的 FastAPI 服务层。

## 启动

从仓库根目录执行：

```bash
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

Swagger：`http://localhost:8000/docs`

## 分层

```text
main.py → AnalysisService → SkillOrchestrator → SkillRegistry → ToolRegistry → Tools
                                      └→ AnalysisStore
```

所有安全关键数值由规则 Tool 计算；真实模型适配器以同名 Tool 替换即可。环境 Tool 对真实坐标采用延迟导入，未安装 GIS 依赖或网络失败时自动返回 `mode=demo-fallback`，不会阻塞服务启动。
