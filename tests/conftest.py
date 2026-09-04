"""共享 SQLite（data/analysis_store.db）的测试清场。

Store 是"启动加载 + 写穿"模型：uvicorn 常驻进程与 pytest 进程各自持有内存副本。
任何一个进程（比如上次中断的测试或 E2E 会话）在库里留下 executing/approved/replanning
任务，后续所有 pytest 进程加载到它后 approve 都会 409（资源已被其他任务锁定）。
每个用例前把这些遗留任务置为 terminated 并清锁——单用例失败不再连坐整个套件。

注意走 `analysis_store._items` 原始字典而不是 `list()`：后者对全部任务做深拷贝，
在大库（数百任务）上每个用例要多花约 2 秒。
"""
import pytest

from backend.app.domain.store import analysis_store

_ACTIVE = {"executing", "approved", "replanning"}


@pytest.fixture(scope="function", autouse=True)
def _terminate_stale_active_tasks():
    for item in list(analysis_store._items.values()):
        if item.status in _ACTIVE:
            analysis_store.release_resources(item.analysis_id)
            analysis_store.update(item.analysis_id, status="terminated")
    yield
