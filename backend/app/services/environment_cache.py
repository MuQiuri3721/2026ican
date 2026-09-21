"""进程内环境数据缓存，提供 TTL、容量上限和过期 stale 读取。

磁盘快照层（BE-23 补强）：每次 set 同步落盘一份最近成功抓取（data/environment_snapshot.json，
单条最新值即可）。进程重启会清空内存缓存——「后端刚重启 + 环境数据源故障（断网/DNS 抖动）」
叠加时，首抓全败且无 stale 可回，曾使 real 模式研判整单 502（round2-5 批量挂实锤）。
get_with_stale 内存未命中时读快照作为最后兜底（值标记 stale，来源如实）。
"""
from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
import os
from time import monotonic
from typing import Any, Optional

_SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "data" / "environment_snapshot.json"


@dataclass
class _Entry:
    value: Any
    expires_at: float


class EnvironmentCache:
    def __init__(self, ttl_seconds: float = 300, max_entries: int = 128, snapshot_path: Optional[Path] = None, snapshot_enabled: Optional[bool] = None):
        if ttl_seconds <= 0 or max_entries <= 0:
            raise ValueError("ttl_seconds 和 max_entries 必须大于 0")
        self.ttl_seconds = float(ttl_seconds)
        self.max_entries = int(max_entries)
        self._items: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = RLock()
        self._snapshot_path = Path(snapshot_path) if snapshot_path else _SNAPSHOT_PATH
        # 磁盘快照默认开启（生产）；pytest conftest 设 ENV_SNAPSHOT_DISK=0 关闭——
        # 契约测试（失败回退演示）依赖"无缓存"语义，磁盘快照会跨用例污染
        self.snapshot_enabled = (os.environ.get("ENV_SNAPSHOT_DISK", "1") != "0") if snapshot_enabled is None else bool(snapshot_enabled)

    def get(self, key: str, allow_stale: bool = False) -> Optional[Any]:
        value, stale = self.get_with_stale(key)
        return value if value is not None and (allow_stale or not stale) else None

    def get_with_stale(self, key: str) -> tuple[Optional[Any], bool]:
        with self._lock:
            entry = self._items.get(key)
            if entry is not None:
                self._items.move_to_end(key)
                return entry.value, monotonic() >= entry.expires_at
        # 内存未命中（进程重启/LRU 淘汰）→ 磁盘快照兜底：值恒视为 stale
        if self.snapshot_enabled:
            snapshot = self._read_snapshot()
            if snapshot is not None:
                return snapshot, True
        return None, False

    def set(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> Any:
        ttl = self.ttl_seconds if ttl_seconds is None else float(ttl_seconds)
        with self._lock:
            self._items[key] = _Entry(value, monotonic() + ttl)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)
        # 磁盘快照：只存 status=ok 的真实成功抓取（由调用方保证），写失败静默（缓存层不拖垮主流程）
        if self.snapshot_enabled:
            try:
                self._write_snapshot(value)
            except Exception:
                pass
        return value

    def _write_snapshot(self, value: Any) -> None:
        self._snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._snapshot_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._snapshot_path)

    def _read_snapshot(self) -> Optional[Any]:
        try:
            return json.loads(self._snapshot_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def clear(self) -> None:
        # 测试清场入口（test_environment_swr 每用例重置缓存态）：内存与磁盘快照同删，
        # 否则快照会跨用例泄漏，无缓存认知的测试读到上一用例数据
        with self._lock:
            self._items.clear()
        try:
            self._snapshot_path.unlink(missing_ok=True)
        except Exception:
            pass


# 服务级共享缓存；只缓存坐标查询，不影响演示场景契约。
environment_cache = EnvironmentCache()
