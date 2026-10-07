"""Live Drama Discovery Service (Turso Cache-First with Background Refresh).

Resolves discovery requests in the following order:
1. In-memory RAM cache if valid (< 15 min).
2. Persistent Turso discovery snapshot (drama_discovery_snapshots).
   - If fresh (<= 15 min): return immediately from Turso (no upstream calls).
   - If stale (> 15 min but <= 7 days): return cached Turso items immediately
     and schedule an asynchronous background refresh without blocking the response.
   - If expired (> 7 days): attempt live refresh synchronously, falling back to
     old snapshot if upstreams fail.
3. If no snapshot exists (empty DB / first boot): call upstreams synchronously,
   persisting results to Turso snapshots + LKG movie cache before responding.
"""

import asyncio
from datetime import datetime, timedelta, timezone
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

FRESH_TTL_SECONDS = 15 * 60  # 15 minutes
MAX_CACHE_AGE_SECONDS = 7 * 24 * 3600  # 7 days

_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_refreshing_keys: set[str] = set()
_refresh_tasks: dict[str, asyncio.Task] = {}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _calc_age_seconds(fetched_at_str: str) -> float:
    try:
        s = (fetched_at_str or "").strip()
        if not s:
            return float("inf")
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now_dt = datetime.now(timezone.utc)
        age = (now_dt - dt).total_seconds()
        return max(0.0, age)
    except Exception:
        return float("inf")


def clear_discovery_cache() -> None:
    """Clear RAM cache and reset refreshing task registries."""
    _cache.clear()
    _refreshing_keys.clear()
    _refresh_tasks.clear()


async def wait_for_refresh(cache_key: str | None = None) -> None:
    """Await in-flight background refresh task(s) (mainly for unit tests)."""
    if cache_key:
        task = _refresh_tasks.get(cache_key)
        if task and not task.done():
            await task
    else:
        tasks = [t for t in _refresh_tasks.values() if not t.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


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


async def _fetch_live(
    *,
    provider: str = "all",
    query: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """Directly fetch series from upstream providers concurrently."""
    norm_provider = (provider or "all").strip().lower()
    norm_query = (query or "").strip()

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

    await asyncio.gather(*[_fetch_one(p) for p in target_providers])

    return {
        "items": all_items,
        "providers": providers_status,
        "errors": errors,
    }


async def _run_background_refresh(
    *,
    provider: str,
    query: str,
    limit: int,
    cache_key: str,
) -> dict[str, Any] | None:
    """Execute background upstream refresh and update Turso + RAM cache safely."""
    live_res = await _fetch_live(
        provider=provider,
        query=query,
        limit=limit,
    )
    items = live_res.get("items") or []

    # Requirement 11: DO NOT OVERWRITE GOOD CACHE WITH BAD RESULT
    # If background refresh returned 0 items and encountered errors, preserve old cache.
    if not items and live_res.get("errors"):
        logger.warning(
            "background refresh for %s produced 0 items with upstream errors; preserving existing snapshot",
            cache_key,
        )
        return None

    try:
        existing_snap = repo.get_discovery_snapshot(cache_key)
        if not items and existing_snap and len(existing_snap.get("items") or []) > 0:
            logger.warning(
                "background refresh for %s produced 0 items while existing snapshot has %d items; preserving existing snapshot",
                cache_key,
                len(existing_snap["items"]),
            )
            return None
    except Exception as exc:
        logger.warning("failed to check existing snapshot during refresh check: %s", exc)

    # Valid result: update movie items and snapshot in Turso
    now_iso = _now()
    if items:
        try:
            repo.upsert_discovery_cache_items(items)
        except Exception as exc:
            logger.warning("failed to persist discovery movie items: %s", exc)

    try:
        repo.upsert_discovery_snapshot(
            cache_key=cache_key,
            provider=provider,
            query=query,
            limit_value=limit,
            items=items,
            provider_status=live_res.get("providers") or {},
            fetched_at=now_iso,
        )
    except Exception as exc:
        logger.warning("failed to persist discovery snapshot: %s", exc)

    response_data = {
        "items": items[: max(1, limit)],
        "providers": live_res.get("providers") or {},
        "errors": live_res.get("errors") or [],
        "source": "live",
        "stale": False,
        "refreshing": False,
        "fetched_at": now_iso,
    }
    _cache[cache_key] = (time.monotonic(), response_data)
    return response_data


def schedule_background_refresh(
    *,
    provider: str,
    query: str,
    limit: int,
) -> bool:
    """Schedule one background refresh per cache_key if not already active."""
    norm_provider = (provider or "all").strip().lower()
    norm_query = (query or "").strip()
    cache_key = f"{norm_provider}:{norm_query.lower()}:{limit}"

    if cache_key in _refreshing_keys:
        return False

    _refreshing_keys.add(cache_key)

    async def _worker() -> None:
        try:
            await _run_background_refresh(
                provider=norm_provider,
                query=norm_query,
                limit=limit,
                cache_key=cache_key,
            )
        except Exception as exc:
            logger.warning("background refresh worker error for %s: %s", cache_key, exc)
        finally:
            _refreshing_keys.discard(cache_key)
            _refresh_tasks.pop(cache_key, None)

    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(_worker())
        _refresh_tasks[cache_key] = task
        return True
    except RuntimeError:
        _refreshing_keys.discard(cache_key)
        return False


async def maybe_warmup_discovery() -> None:
    """Startup warmup: check default discovery snapshot (all::20).

    If missing or stale, schedule background refresh without blocking startup.
    """
    try:
        cache_key = "all::20"
        snapshot = repo.get_discovery_snapshot(cache_key)
        if snapshot is None or not snapshot.get("items"):
            logger.info("startup warmup: default discovery snapshot missing, scheduling refresh")
            schedule_background_refresh(provider="all", query="", limit=20)
        else:
            age = _calc_age_seconds(snapshot.get("fetched_at") or "")
            if age > FRESH_TTL_SECONDS:
                logger.info(
                    "startup warmup: default discovery snapshot stale (age=%.0fs), scheduling refresh",
                    age,
                )
                schedule_background_refresh(provider="all", query="", limit=20)
            else:
                logger.info("startup warmup: default discovery snapshot is fresh (age=%.0fs)", age)
    except Exception as exc:
        logger.warning("startup warmup check failed: %s", exc)


async def discover_movies(
    *,
    provider: str = "all",
    query: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """Cache-first discovery endpoint with background refresh."""
    norm_provider = (provider or "all").strip().lower()
    norm_query = (query or "").strip()
    norm_limit = max(1, int(limit or 20))
    cache_key = f"{norm_provider}:{norm_query.lower()}:{norm_limit}"

    now_mono = time.monotonic()

    # 1. RAM cache if valid (< 15 min)
    if cache_key in _cache:
        cached_mono, cached_res = _cache[cache_key]
        if now_mono - cached_mono < FRESH_TTL_SECONDS:
            return cached_res

    # 2. Turso discovery snapshot
    snapshot: dict[str, Any] | None = None
    try:
        snapshot = repo.get_discovery_snapshot(cache_key)
    except Exception as exc:
        logger.warning("failed to retrieve discovery snapshot for %s: %s", cache_key, exc)

    if snapshot is not None and snapshot.get("items"):
        fetched_at_str = snapshot.get("fetched_at") or _now()
        age_seconds = _calc_age_seconds(fetched_at_str)
        items = snapshot.get("items") or []
        provider_status = snapshot.get("provider_status") or {}

        if age_seconds <= FRESH_TTL_SECONDS:
            # Fresh (< 15 min): return immediately, zero upstream calls
            response_data = {
                "items": items[:norm_limit],
                "providers": provider_status,
                "errors": [],
                "source": "cache",
                "stale": False,
                "refreshing": False,
                "fetched_at": fetched_at_str,
            }
            _cache[cache_key] = (now_mono, response_data)
            return response_data

        elif age_seconds <= MAX_CACHE_AGE_SECONDS:
            # Stale (> 15 min and <= 7 days): return Turso immediately, schedule background refresh
            schedule_background_refresh(
                provider=norm_provider,
                query=norm_query,
                limit=norm_limit,
            )
            response_data = {
                "items": items[:norm_limit],
                "providers": provider_status,
                "errors": [],
                "source": "cache",
                "stale": True,
                "refreshing": True,
                "fetched_at": fetched_at_str,
            }
            # Cache in RAM briefly so burst traffic doesn't re-read DB before refresh completes
            _cache[cache_key] = (now_mono, response_data)
            return response_data

        else:
            # age > MAX_CACHE_AGE_SECONDS (> 7 days): attempt live refresh synchronously,
            # retaining snapshot as emergency fallback if upstreams fail.
            pass

    # 3. Synchronous live fetch (either no snapshot, or snapshot > 7 days)
    live_res = await _fetch_live(
        provider=norm_provider,
        query=norm_query,
        limit=norm_limit,
    )
    items = live_res.get("items") or []
    providers_status = live_res.get("providers") or {}
    errors = live_res.get("errors") or []

    if items:
        # Success: SAVE TO TURSO BEFORE considering request complete
        now_iso = _now()
        try:
            repo.upsert_discovery_cache_items(items)
        except Exception as exc:
            logger.warning("failed to persist discovery cache items: %s", exc)

        try:
            repo.upsert_discovery_snapshot(
                cache_key=cache_key,
                provider=norm_provider,
                query=norm_query,
                limit_value=norm_limit,
                items=items,
                provider_status=providers_status,
                fetched_at=now_iso,
            )
        except Exception as exc:
            logger.warning("failed to persist discovery snapshot: %s", exc)

        response_data = {
            "items": items[:norm_limit],
            "providers": providers_status,
            "errors": errors,
            "source": "live",
            "stale": False,
            "refreshing": False,
            "fetched_at": now_iso,
        }
        _cache[cache_key] = (now_mono, response_data)
        return response_data

    # Live returned NO items: check emergency fallback to older (> 7 days) snapshot
    if snapshot is not None and snapshot.get("items"):
        items = snapshot.get("items") or []
        provider_status = snapshot.get("provider_status") or {}
        response_data = {
            "items": items[:norm_limit],
            "providers": provider_status,
            "errors": errors,
            "source": "cache",
            "stale": True,
            "refreshing": False,
            "fetched_at": snapshot.get("fetched_at") or _now(),
        }
        _cache[cache_key] = (now_mono, response_data)
        return response_data

    # Check LKG movie items table if available
    try:
        lkg_items = repo.get_discovery_cache_items(
            provider=norm_provider,
            query=norm_query,
            limit=norm_limit,
            max_age_hours=24 * 7,
        )
        if lkg_items:
            now_iso = _now()
            try:
                repo.upsert_discovery_snapshot(
                    cache_key=cache_key,
                    provider=norm_provider,
                    query=norm_query,
                    limit_value=norm_limit,
                    items=lkg_items,
                    provider_status=providers_status,
                    fetched_at=now_iso,
                )
            except Exception:
                pass
            response_data = {
                "items": lkg_items[:norm_limit],
                "providers": providers_status,
                "errors": errors,
                "source": "cache",
                "stale": True,
                "refreshing": False,
                "fetched_at": now_iso,
            }
            _cache[cache_key] = (now_mono, response_data)
            return response_data
    except Exception as exc:
        logger.warning("failed to retrieve LKG cache: %s", exc)

    # Clean empty response
    response_data = {
        "items": [],
        "providers": providers_status,
        "errors": errors,
        "source": "live",
        "stale": False,
        "refreshing": False,
        "fetched_at": _now(),
    }
    _cache[cache_key] = (now_mono, response_data)
    return response_data
