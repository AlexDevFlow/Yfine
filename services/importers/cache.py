"""In-memory TTL cache for import preview payloads (15 min default)."""
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

_TTL_SECONDS = 15 * 60


@dataclass
class _CacheEntry:
    payload: Any
    expires_at: float


_store: dict[str, _CacheEntry] = {}
_lock = threading.Lock()


def _prune_locked() -> None:
    now = time.time()
    stale = [k for k, v in _store.items() if v.expires_at <= now]
    for k in stale:
        _store.pop(k, None)


def put(payload: Any, ttl: int = _TTL_SECONDS) -> str:
    pid = uuid.uuid4().hex
    with _lock:
        _prune_locked()
        _store[pid] = _CacheEntry(payload=payload, expires_at=time.time() + ttl)
    return pid


def get(pid: str) -> Any | None:
    with _lock:
        _prune_locked()
        entry = _store.get(pid)
        if entry is None:
            return None
        return entry.payload


def invalidate(pid: str) -> None:
    with _lock:
        _store.pop(pid, None)


def clear() -> None:
    with _lock:
        _store.clear()
