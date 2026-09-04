"""FastAPI 应用装配（开发者 A 所有）。

路由按域拆分在 routes/ 下：task_routes（任务/平台，A）与 environment_routes（环境/等高线，B），
两位平台开发者并行开发时不共享任何路由文件（CONTRIBUTING.md 第 3、4 节）。
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes.environment_routes import router as environment_router
from .routes.task_routes import router as task_router


app = FastAPI(title="Forest Fire Rescue Agent", version="0.3.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:5175", "http://127.0.0.1:5173", "http://127.0.0.1:5174", "http://127.0.0.1:5175"], allow_methods=["*"], allow_headers=["*"])
app.include_router(task_router)
app.include_router(environment_router)
