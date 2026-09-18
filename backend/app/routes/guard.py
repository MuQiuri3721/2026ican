"""演示态指挥员口令门（FE-71）。

仅在环境变量 FIREOPS_COMMANDER_TOKEN 配置时启用：全部 POST 变更路由要求
携带同值 `X-Commander-Token` 请求头，否则 401。未配置 = 开放模式（本地演示
与 E2E 回归不受影响）。口令在每次请求时读环境变量，改配置后端重启即可生效。
"""
import os

from fastapi import HTTPException, Request


def require_commander(request: Request) -> None:
    expected = (os.getenv("FIREOPS_COMMANDER_TOKEN") or "").strip()
    if not expected:
        return
    supplied = request.headers.get("X-Commander-Token", "")
    if supplied != expected:
        raise HTTPException(status_code=401, detail="需要指挥员口令（X-Commander-Token 请求头）")
