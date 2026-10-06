"""Live state shared between the API and the engine.

* inbox     - messages from phones/dashboards for the engine (scans, GPS, manual picks, sim commands)
* snapshots - latest per-building live picture (dashboard initial load, REST polling fallback)
* devices   - latest fix + route per device (app reconnects, offline resync)

Redis when ``REDIS_URL`` is set (API and engine in separate processes), otherwise in-process memory.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from typing import Any, Protocol


class LiveStore(Protocol):
    def push_inbox(self, msg: dict) -> None: ...
    def drain_inbox(self, limit: int = 2000) -> list[dict]: ...
    def set_snapshot(self, building_id: int, snapshot: dict) -> None: ...
    def get_snapshot(self, building_id: int) -> dict | None: ...
    def set_device(self, device_id: str, state: dict) -> None: ...
    def get_device(self, device_id: str) -> dict | None: ...
    def set_json(self, key: str, value: Any, ttl_s: int | None = None) -> None: ...
    def get_json(self, key: str) -> Any: ...


class MemoryStore:
    def __init__(self) -> None:
        self._inbox: deque[dict] = deque()
        self._kv: dict[str, Any] = {}
        self._lock = threading.Lock()

    def push_inbox(self, msg: dict) -> None:
        with self._lock:
            self._inbox.append(msg)

    def drain_inbox(self, limit: int = 2000) -> list[dict]:
        out = []
        with self._lock:
            while self._inbox and len(out) < limit:
                out.append(self._inbox.popleft())
        return out

    def set_snapshot(self, building_id: int, snapshot: dict) -> None:
        self._kv[f"snapshot:{building_id}"] = snapshot

    def get_snapshot(self, building_id: int) -> dict | None:
        return self._kv.get(f"snapshot:{building_id}")

    def set_device(self, device_id: str, state: dict) -> None:
        self._kv[f"device:{device_id}"] = state

    def get_device(self, device_id: str) -> dict | None:
        return self._kv.get(f"device:{device_id}")

    def set_json(self, key: str, value: Any, ttl_s: int | None = None) -> None:
        self._kv[key] = value

    def get_json(self, key: str) -> Any:
        return self._kv.get(key)


class RedisStore:
    PREFIX = "fire:"

    def __init__(self, url: str) -> None:
        import redis

        self.r = redis.Redis.from_url(url, decode_responses=True)

    def push_inbox(self, msg: dict) -> None:
        self.r.rpush(self.PREFIX + "inbox", json.dumps(msg))

    def drain_inbox(self, limit: int = 2000) -> list[dict]:
        pipe = self.r.pipeline()
        pipe.lrange(self.PREFIX + "inbox", 0, limit - 1)
        pipe.ltrim(self.PREFIX + "inbox", limit, -1)
        raw, _ = pipe.execute()
        return [json.loads(m) for m in raw]

    def set_snapshot(self, building_id: int, snapshot: dict) -> None:
        self.r.set(f"{self.PREFIX}snapshot:{building_id}", json.dumps(snapshot), ex=3600)

    def get_snapshot(self, building_id: int) -> dict | None:
        raw = self.r.get(f"{self.PREFIX}snapshot:{building_id}")
        return json.loads(raw) if raw else None

    def set_device(self, device_id: str, state: dict) -> None:
        self.r.set(f"{self.PREFIX}device:{device_id}", json.dumps(state), ex=24 * 3600)

    def get_device(self, device_id: str) -> dict | None:
        raw = self.r.get(f"{self.PREFIX}device:{device_id}")
        return json.loads(raw) if raw else None

    def set_json(self, key: str, value: Any, ttl_s: int | None = None) -> None:
        self.r.set(self.PREFIX + key, json.dumps(value), ex=ttl_s)

    def get_json(self, key: str) -> Any:
        raw = self.r.get(self.PREFIX + key)
        return json.loads(raw) if raw else None


_store: LiveStore | None = None


def init_store(redis_url: str) -> LiveStore:
    global _store
    _store = RedisStore(redis_url) if redis_url else MemoryStore()
    return _store


def get_store() -> LiveStore:
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store
