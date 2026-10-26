"""Dashboard read cache — reduces DB load on polling dashboard views."""

import asyncio
import logging
import time
from typing import Any, Callable

from ..config import settings

logger = logging.getLogger("backend-tiktok.services.dashboard_cache")

_cache: dict[str, tuple[float, Any]] = {}
_ttl = max(settings.tiktok_flow_cache_seconds, 5)


def _now() -> float:
    return time.time()


async def get_cached(key: str, loader: Callable[[], Any]) -> Any:
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < _ttl:
        return entry[1]
    data = await loader()
    _cache[key] = (_now(), data)
    return data


def invalidate(key: str) -> None:
    _cache.pop(key, None)


def invalidate_pipeline(pipeline_id: str) -> None:
    for k in list(_cache.keys()):
        if k.startswith(f"pipeline:{pipeline_id}"):
            _cache.pop(k, None)


def clear_all() -> None:
    _cache.clear()
