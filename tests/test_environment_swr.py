"""BE-15 · 环境缓存 SWR（过期回 stale + 后台单飞刷新）契约测试。"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.services import environment_service  # noqa: E402
from backend.app.services.environment_cache import environment_cache  # noqa: E402
from backend.app.tools.environment import EnvironmentTool  # noqa: E402


def test_stale_served_immediately_and_background_refreshes(monkeypatch):
    tool = EnvironmentTool()
    lat, lng = 32.10, 118.85
    environment_cache.clear()
    # 载荷形状对齐真实服务：_normalize 从 raw.weather.wind_speed_m_s 取风速
    payload = {"status": "ok", "location": {"latitude": lat, "longitude": lng},
               "weather": {"wind_speed_m_s": 3.0}}

    # 1) 首次在线抓取入缓存
    monkeypatch.setattr(environment_service, "get_environment", lambda *a, **k: dict(payload))
    first = tool.run(scene_id="forest-demo-01", latitude=lat, longitude=lng, environment_mode="real")
    assert first["status"] == "ok" and first["wind_speed"] == 3.0

    # 2) 后台刷新挂 1.5s 慢源：SWR 必须立即回 stale，不等慢源。
    # cache_key 含 id(get_environment) 标记：patch 后按新函数重算键并写入过期条目
    calls = {"n": 0}

    def slow_fetch(*a, **k):
        calls["n"] += 1
        time.sleep(1.5)
        return {"status": "ok", "location": {"latitude": lat, "longitude": lng},
                "weather": {"wind_speed_m_s": 5.0}}

    monkeypatch.setattr(environment_service, "get_environment", slow_fetch)
    # 键算法与 run() 同口径（module.qualname 标记，BE-15 后弃用 id(fn)）
    fn_marker = f"{getattr(slow_fetch, '__module__', '')}.{getattr(slow_fetch, '__qualname__', '')}"
    key = f"{lat:.6f}:{lng:.6f}:5000:5000:{fn_marker}"
    environment_cache.set(key, first, ttl_seconds=0.05)
    time.sleep(0.1)

    t0 = time.time()
    stale = tool.run(scene_id="forest-demo-01", latitude=lat, longitude=lng, environment_mode="real")
    elapsed = time.time() - t0
    assert elapsed < 1.0, elapsed
    assert stale["status"] == "stale" and stale["stale"] is True
    assert stale["fallback"]["code"] == "environment_stale"

    # 3) 刷新在途时的并发请求：单飞（后台线程仍在跑），立即回 stale
    again = tool.run(scene_id="forest-demo-01", latitude=lat, longitude=lng, environment_mode="real")
    assert again["status"] == "stale"

    # 4) 后台刷新落地后：缓存回新（轮询等后台线程写库，上限 5s）
    deadline = time.time() + 5
    fresh, is_stale = (None, True)
    while time.time() < deadline:
        fresh, is_stale = environment_cache.get_with_stale(key)
        if fresh is not None and not is_stale and fresh.get("wind_speed") == 5.0:
            break
        time.sleep(0.2)
    assert calls["n"] == 1, calls
    assert fresh is not None and not is_stale and fresh.get("wind_speed") == 5.0, (fresh, is_stale)
