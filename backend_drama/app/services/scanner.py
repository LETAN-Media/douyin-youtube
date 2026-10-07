"""Source scanner: resolve series, enumerate episodes, persist inventory.

No media is ever downloaded. First scan stores everything; later scans
are incremental (only new episodes inserted, changed metadata updated).

Live runs go through the failover pool (provider selected from
source.provider); injected fakes keep unit tests hermetic.
"""

import logging
from typing import Any

import httpx

from ..db.repositories import drama as repo
from ..models.drama import EpisodePage
from .providers.base import ProviderError
from .rapidix import RapidixError

logger = logging.getLogger("backend-drama-scanner")

_POOL_ERROR_CODES = frozenset({
    "ALL_PROVIDERS_FAILED", "CONFIG_ERROR", "NOT_FOUND", "NOT_CONFIGURED",
    "UNSUPPORTED", "UNSUPPORTED_PROVIDER", "TEMPORARY", "TIMEOUT",
    "RATE_LIMITED", "INVALID_RESPONSE", "AUTH_FAILED",
    "RAPIDIX_EPISODES_INVALID_REQUEST", "RAPIDIX_SERIES_NOT_FOUND",
    "RAPIDIX_UPSTREAM_ERROR", "RAPIDIX_RATE_LIMITED",
})


def client_has_detail(client: Any) -> bool:
    """Providers without a series-detail endpoint (or test fakes) are
    skipped: the shell row is enough to enumerate episodes."""
    return callable(getattr(client, "get_series", None))


async def _via_pool(provider_name: str, operation: str,
                    transport: httpx.AsyncBaseTransport | None,
                    source_id: str, **kwargs: Any) -> Any:
    from .providers import pool as pool_mod

    result, endpoint_name = await pool_mod.execute(
        provider_name, operation, transport=transport, **kwargs
    )
    logger.info("drama scan source=%s served by endpoint=%s", source_id, endpoint_name)
    return result


async def scan_source(
    source_id: str,
    *,
    client=None,
    transport: httpx.AsyncBaseTransport | None = None,
    max_pages: int = 20,
) -> dict[str, Any]:
    source = repo.get_source(source_id)
    if source is None:
        raise ValueError(f"Source not found: {source_id}")
    if not source.get("enabled", True):
        return {
            "source_id": source_id, "series_found": 0, "episodes_found": 0,
            "inserted": 0, "existing": 0, "updated": 0, "skipped": True,
        }
    provider_name = (source.get("provider") or "rapidix").strip().lower()
    use_pool = client is None

    external_series_id = source.get("external_series_id")
    if not external_series_id:
        raise RapidixError(
            "NOT_CONFIGURED",
            "Source has no external_series_id yet (search-to-source flow lands in Phase 2).",
        )

    async def _detail(sid: str) -> Any | None:
        try:
            if use_pool:
                return await _via_pool(
                    provider_name, "get_series", transport, source_id,
                    series_id=sid,
                )
            if client_has_detail(client):
                return await client.get_series(sid)
            return None
        except Exception:
            return None

    async def _page(sid: str, cursor: str | None) -> EpisodePage:
        try:
            if use_pool:
                return await _via_pool(
                    provider_name, "list_episodes", transport, source_id,
                    series_id=sid, cursor=cursor,
                )
            assert client is not None
            return await client.list_episodes(sid, cursor=cursor)
        except (RapidixError, ProviderError, Exception) as exc:
            code = getattr(exc, "code", None)
            if code in _POOL_ERROR_CODES:
                raise RapidixError(code, str(exc) or "Provider failed.")
            raise

    # Series shell first (detail filled when the provider has an endpoint).
    series_row, _ = repo.upsert_series(
        source_id=source_id, provider=provider_name,
        external_series_id=external_series_id,
        title=source.get("name"),
    )
    detail = await _detail(external_series_id)
    if detail is not None:
        series_row, _ = repo.upsert_series(
            source_id=source_id, provider=provider_name,
            external_series_id=external_series_id,
            title=detail.title or source.get("name"),
            description=detail.description,
            thumbnail_url=detail.thumbnail_url,
            total_episodes=detail.total_episodes,
            metadata={"raw": detail.raw},
        )

    inserted = existing = updated = 0
    found = 0
    cursor: str | None = source.get("scan_cursor")
    series_found = 1
    for _ in range(max(1, max_pages)):
        page = await _page(external_series_id, cursor)
        if not page.episodes:
            break
        # Sort numerically
        for ep in sorted(page.episodes, key=lambda e: int(e.episode_number)):
            found += 1
            ep_title = ep.title or f"Tập {ep.episode_number}"
            _, outcome = repo.upsert_episode(
                series_id=series_row["id"], provider=ep.provider,
                external_episode_id=ep.external_episode_id or f"{external_series_id}:{ep.episode_number}",
                episode_number=int(ep.episode_number), title=ep_title,
                source_url=ep.source_url, thumbnail_url=ep.thumbnail_url,
                duration=ep.duration,
            )
            if outcome == "inserted":
                inserted += 1
            elif outcome == "updated":
                updated += 1
            else:
                existing += 1
        cursor = page.next_cursor
        if not page.has_more or not cursor:
            cursor = None
            break

    if found > 0:
        repo.upsert_series(
            source_id=source_id, provider=provider_name,
            external_series_id=external_series_id,
            total_episodes=max(found, (detail.total_episodes or 0) if detail else 0),
        )

    repo.touch_source(source_id, scan_cursor=cursor)
    logger.info(
        "drama scan source=%s series=%s found=%d inserted=%d existing=%d updated=%d",
        source_id, series_row["id"], found, inserted, existing, updated,
    )
    return {
        "source_id": source_id,
        "series_id": series_row["id"],
        "series_found": series_found,
        "episodes_found": found,
        "inserted": inserted,
        "existing": existing,
        "updated": updated,
    }
