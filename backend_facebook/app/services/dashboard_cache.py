"""Short-lived cache for dashboard read models.

Never used by publisher, scheduler, quota, or AI workers. Disabled for local
file databases so tests and development always see fresh rows.
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, TypeVar

from ..config import settings

T = TypeVar("T")

_cache: dict[str, tuple[float, object]] = {}
_lock = asyncio.Lock()


def _enabled(ttl_seconds: int) -> bool:
    if ttl_seconds <= 0:
        return False
    url = (settings.TURSO_DATABASE_URL or "").strip().lower()
    return url.startswith(("http://", "https://", "libsql://"))


async def get_or_compute(
    key: str,
    ttl_seconds: int,
    compute: Callable[[], Awaitable[T]],
) -> T:
    if not _enabled(ttl_seconds):
        return await compute()

    now = time.monotonic()
    async with _lock:
        entry = _cache.get(key)
        if entry is not None and entry[0] > now:
            return entry[1]  # type: ignore[return-value]

    value = await compute()
    async with _lock:
        _cache[key] = (time.monotonic() + ttl_seconds, value)
        if len(_cache) > 64:
            cutoff = time.monotonic()
            for cached_key, (expires_at, _) in list(_cache.items()):
                if expires_at <= cutoff:
                    _cache.pop(cached_key, None)
    return value


def clear() -> None:
    if _cache:
        _cache.clear()
