"""FastAPI 应用装配（开发者 A 所有）。

路由按域拆分在 routes/ 下：task_routes（任务/平台，A）与 environment_routes（环境/等高线，B），
两位平台开发者并行开发时不共享任何路由文件（CONTRIBUTING.md 第 3、4 节）。
"""
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes.assistant_routes import router as assistant_router
from .routes.environment_routes import router as environment_router
from .routes.task_routes import router as task_router
from .tools.environment import DEFAULT_LATITUDE, DEFAULT_LONGITUDE, EnvironmentTool


def _load_env() -> None:
    """加载仓库根 .env（FE-22：GLM 解释层密钥不入库）；已设置的真实环境变量优先。"""
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_env()


def _warm_environment_cache() -> None:
    """后台预热默认演示场景（紫金山）的真实环境缓存。

    Overpass 镜像链路冷启动可达 30-60s；演示开机即取环境不应让操作员等待。
    预热失败保持静默：首个真实请求会走正常抓取链路。
    """
    try:
        EnvironmentTool().run(
            scene_id="forest-demo-01",
            latitude=DEFAULT_LATITUDE,
            longitude=DEFAULT_LONGITUDE,
            environment_mode="real",
        )
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_: FastAPI):
    threading.Thread(target=_warm_environment_cache, daemon=True, name="environment-warmup").start()
    yield


app = FastAPI(title="Forest Fire Rescue Agent", version="0.3.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:5175", "http://127.0.0.1:5173", "http://127.0.0.1:5174", "http://127.0.0.1:5175"], allow_methods=["*"], allow_headers=["*"])
app.include_router(task_router)
app.include_router(environment_router)
app.include_router(assistant_router)
