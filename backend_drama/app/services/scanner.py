"""Source scanner: resolve series, enumerate episodes, persist inventory.

No media is ever downloaded. First scan stores everything; later scans
are incremental (only new episodes inserted, changed metadata updated).
"""

import logging
from typing import Any

import httpx

from ..db.repositories import drama as repo
from ..models.drama import EpisodePage
from .providers import get_provider
from .providers.base import ProviderError
from .rapidix import RapidixError

logger = logging.getLogger("backend-drama-scanner")


def client_has_detail(client: Any) -> bool:
    """Providers without a series-detail endpoint (or test fakes) are
    skipped: the shell row is enough to enumerate episodes."""
    return callable(getattr(client, "get_series", None))


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
    if client is None:
        try:
            client = get_provider(provider_name, transport=transport)
        except ProviderError as exc:
            raise RapidixError("UNSUPPORTED_PROVIDER", str(exc))

    external_series_id = source.get("external_series_id")
    if not external_series_id:
        raise RapidixError(
            "NOT_CONFIGURED",
            "Source has no external_series_id yet (search-to-source flow lands in Phase 2).",
        )

    # Series shell first (detail filled when the provider has an endpoint).
    series_row, _ = repo.upsert_series(
        source_id=source_id, provider=provider_name,
        external_series_id=external_series_id,
    )
    if client_has_detail(client):
        try:
            detail = await client.get_series(external_series_id)
        except Exception:
            detail = None
        if detail is not None:
            series_row, _ = repo.upsert_series(
                source_id=source_id, provider=provider_name,
                external_series_id=external_series_id,
                title=detail.title, description=detail.description,
                thumbnail_url=detail.thumbnail_url,
                total_episodes=detail.total_episodes,
                metadata={"raw": detail.raw},
            )

    inserted = existing = updated = 0
    found = 0
    cursor: str | None = source.get("scan_cursor")
    series_found = 1
    for _ in range(max(1, max_pages)):
        try:
            page: EpisodePage = await client.list_episodes(
                external_series_id, cursor=cursor
            )
        except (RapidixError, ProviderError):
            raise
        if not page.episodes:
            break
        for ep in page.episodes:
            found += 1
            _, outcome = repo.upsert_episode(
                series_id=series_row["id"], provider=ep.provider,
                external_episode_id=ep.external_episode_id,
                episode_number=ep.episode_number, title=ep.title,
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
