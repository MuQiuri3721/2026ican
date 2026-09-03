"""进程内环境数据缓存，提供 TTL、容量上限和过期 stale 读取。"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Any, Optional


@dataclass
class _Entry:
    value: Any
    expires_at: float


class EnvironmentCache:
    def __init__(self, ttl_seconds: float = 300, max_entries: int = 128):
        if ttl_seconds <= 0 or max_entries <= 0:
            raise ValueError("ttl_seconds 和 max_entries 必须大于 0")
        self.ttl_seconds = float(ttl_seconds)
        self.max_entries = int(max_entries)
        self._items: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = RLock()

    def get(self, key: str, allow_stale: bool = False) -> Optional[Any]:
        value, stale = self.get_with_stale(key)
        return value if value is not None and (allow_stale or not stale) else None

    def get_with_stale(self, key: str) -> tuple[Optional[Any], bool]:
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None, False
            self._items.move_to_end(key)
            return entry.value, monotonic() >= entry.expires_at

    def set(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> Any:
        ttl = self.ttl_seconds if ttl_seconds is None else float(ttl_seconds)
        with self._lock:
            self._items[key] = _Entry(value, monotonic() + ttl)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)
        return value

    def delete(self, key: str) -> None:
        with self._lock:
            self._items.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


# 服务级共享缓存；只缓存坐标查询，不影响演示场景契约。
environment_cache = EnvironmentCache()
