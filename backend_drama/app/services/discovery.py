"""Live Drama Discovery Service (multi-provider aggregation & last-known-good cache).

Fetches live series directly from upstream Drama providers via the failover pool.
When live upstreams succeed, series metadata is cached in persistent LKG storage
(Turso drama_discovery_cache). If live upstreams temporarily fail, recent cached
metadata is returned with stale=True so users can continue browsing.
"""

import asyncio
import logging
import time
from typing import Any

from ..db.repositories import drama as repo
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

CACHE_TTL_SECONDS = 15 * 60  # 15 minutes RAM cache
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def clear_discovery_cache() -> None:
    _cache.clear()


def normalize_provider_error(
    provider: str,
    code: str | None = None,
    raw_message: str = "",
) -> dict[str, Any]:
    """Map internal error codes into a typed, public diagnostic dictionary."""
    c = (code or "").strip().upper()
    if c == "RATE_LIMITED":
        status = "rate_limited"
        msg = "Nguồn phim đang bị giới hạn tần suất yêu cầu. Vui lòng thử lại sau."
        retryable = True
    elif c in ("UNSUPPORTED", "UNSUPPORTED_PROVIDER", "NOT_SUPPORTED"):
        status = "not_supported"
        msg = "Nguồn phim không hỗ trợ tính năng này."
        retryable = False
    elif c in ("CONFIG_ERROR", "AUTH_FAILED", "NOT_CONFIGURED", "SUBSCRIPTION_ERROR"):
        status = "upstream_error"
        msg = "Cấu hình nguồn phim chưa hoàn tất hoặc gặp lỗi kết nối."
        retryable = False
    elif c in ("ALL_PROVIDERS_FAILED", "VENDOR_DOWN", "TEMPORARY", "TIMEOUT", "UNAVAILABLE", "NETWORK", "HOST_UNREACHABLE", "ERROR"):
        status = "temporarily_unavailable"
        msg = "Nguồn phim tạm thời không khả dụng."
        retryable = True
    else:
        status = "upstream_error"
        msg = "Nguồn phim tạm thời không khả dụng."
        retryable = True

    return {
        "provider": provider,
        "status": status,
        "code": c or "ERROR",
        "message": msg,
        "retryable": retryable,
    }


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
            norm_err = normalize_provider_error(p_name, code=code, raw_message=str(exc))
            providers_status[p_name] = {
                "status": norm_err["status"],
                "code": norm_err["code"],
                "message": norm_err["message"],
                "retryable": norm_err["retryable"],
            }
            errors.append(norm_err)
        except ProviderError as exc:
            norm_err = normalize_provider_error(p_name, code=exc.code, raw_message=str(exc))
            providers_status[p_name] = {
                "status": norm_err["status"],
                "code": norm_err["code"],
                "message": norm_err["message"],
                "retryable": norm_err["retryable"],
            }
            errors.append(norm_err)
        except Exception as exc:
            logger.warning("discovery error on provider=%s: %s", p_name, exc)
            norm_err = normalize_provider_error(p_name, code="ERROR", raw_message=str(exc))
            providers_status[p_name] = {
                "status": norm_err["status"],
                "code": norm_err["code"],
                "message": norm_err["message"],
                "retryable": norm_err["retryable"],
            }
            errors.append(norm_err)

    # Fetch providers concurrently
    await asyncio.gather(*[_fetch_one(p) for p in target_providers])

    source = "live"
    stale = False

    # Persistent Last-Known-Good cache handling
    if all_items:
        # Live success: update persistent LKG cache
        try:
            repo.upsert_discovery_cache_items(all_items)
        except Exception as exc:
            logger.warning("failed to persist discovery cache: %s", exc)
    else:
        # Live upstreams returned no items (e.g. outage or temporary failure)
        # Attempt fallback to persistent LKG cache
        try:
            lkg_items = repo.get_discovery_cache_items(
                provider=norm_provider,
                query=norm_query,
                limit=limit,
                max_age_hours=24,
            )
            if lkg_items:
                all_items = lkg_items
                source = "cache"
                stale = True
        except Exception as exc:
            logger.warning("failed to retrieve LKG cache: %s", exc)

    response_data = {
        "items": all_items[: max(1, limit)],
        "providers": providers_status,
        "errors": errors,
        "source": source,
        "stale": stale,
    }

    # Cache successful responses or partial/LKG results in RAM
    if all_items or not errors:
        _cache[cache_key] = (now, response_data)

    return response_data
