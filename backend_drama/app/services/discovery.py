"""Live Drama Discovery Service (multi-provider aggregation & in-memory cache).

Fetches live series directly from upstream Drama providers (Short Drama Pro hub, etc.)
via the failover pool. Discovery results are never persisted automatically.
"""

import asyncio
import logging
import time
from typing import Any

from .providers import pool as pool_mod
from .providers.base import ProviderError

logger = logging.getLogger("backend-drama-discovery")

# Candidate providers for default feed discovery (must have real feed endpoints)
FEED_DISCOVERY_PROVIDERS = ("netshort", "shortmax")

# Candidate providers for keyword search
KEYWORD_SEARCH_PROVIDERS = (
    "starshort",
    "dramabox",
    "flickshort",
    "reelshort_sdp",
    "rapidix",
)

CACHE_TTL_SECONDS = 15 * 60  # 15 minutes
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def clear_discovery_cache() -> None:
    _cache.clear()


async def discover_movies(
    *,
    provider: str = "all",
    query: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    norm_provider = (provider or "all").strip().lower()
    norm_query = (query or "").strip()
    cache_key = f"{norm_provider}:{norm_query.lower()}:{limit}"

    now = time.monotonic()
    if cache_key in _cache:
        cached_time, cached_res = _cache[cache_key]
        if now - cached_time < CACHE_TTL_SECONDS:
            return cached_res

    # Determine providers to query
    if norm_provider == "all":
        if not norm_query:
            target_providers = list(FEED_DISCOVERY_PROVIDERS)
            op = "discover_series"
        else:
            target_providers = list(KEYWORD_SEARCH_PROVIDERS)
            op = "search_series"
    else:
        target_providers = [norm_provider]
        op = "search_series" if norm_query else "discover_series"

    all_items: list[dict[str, Any]] = []
    providers_status: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    async def _fetch_one(p_name: str) -> None:
        try:
            if op == "discover_series":
                series_list, upstream = await pool_mod.execute(
                    p_name, "discover_series", limit=limit
                )
            else:
                series_list, upstream = await pool_mod.execute(
                    p_name, "search_series", query=norm_query, limit=limit
                )

            count = 0
            if isinstance(series_list, list):
                for s in series_list:
                    pair = (s.provider, s.external_series_id)
                    if pair not in seen:
                        seen.add(pair)
                        all_items.append(
                            {
                                "provider": s.provider,
                                "external_series_id": s.external_series_id,
                                "title": s.title,
                                "description": s.description,
                                "thumbnail_url": s.thumbnail_url,
                                "total_episodes": s.total_episodes,
                            }
                        )
                        count += 1

            providers_status[p_name] = {
                "status": "ok",
                "count": count,
                "upstream": upstream,
            }
        except pool_mod.PoolExhausted as exc:
            code = getattr(exc, "code", "UNAVAILABLE")
            if code == "UNSUPPORTED":
                providers_status[p_name] = {
                    "status": "unsupported",
                    "reason": "Provider does not support this operation",
                }
            else:
                providers_status[p_name] = {"status": "error", "code": code}
                errors.append(
                    {
                        "provider": p_name,
                        "code": code,
                        "message": str(exc),
                    }
                )
        except ProviderError as exc:
            if exc.code == "UNSUPPORTED":
                providers_status[p_name] = {
                    "status": "unsupported",
                    "reason": "Provider does not support this operation",
                }
            else:
                providers_status[p_name] = {"status": "error", "code": exc.code}
                errors.append(
                    {
                        "provider": p_name,
                        "code": exc.code,
                        "message": str(exc),
                    }
                )
        except Exception as exc:
            logger.warning("discovery error on provider=%s: %s", p_name, exc)
            providers_status[p_name] = {"status": "error", "code": "ERROR"}
            errors.append(
                {
                    "provider": p_name,
                    "code": "ERROR",
                    "message": str(exc),
                }
            )

    # Fetch providers concurrently
    await asyncio.gather(*[_fetch_one(p) for p in target_providers])

    response_data = {
        "items": all_items[: max(1, limit)],
        "providers": providers_status,
        "errors": errors,
    }

    # Cache successful responses or partial results
    if all_items or not errors:
        _cache[cache_key] = (now, response_data)

    return response_data
