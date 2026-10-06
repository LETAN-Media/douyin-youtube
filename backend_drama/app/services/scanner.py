"""Source scanner: resolve series, enumerate episodes, persist inventory.

No media is ever downloaded. First scan stores everything; later scans
are incremental (only new episodes inserted, changed metadata updated).
"""

import logging
from typing import Any

import httpx

from ..db.repositories import drama as repo
from ..models.drama import EpisodePage
from .rapidix import PROVIDER, RapidixClient, RapidixError

logger = logging.getLogger("backend-drama-scanner")


async def scan_source(
    source_id: str,
    *,
    client: RapidixClient | None = None,
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
    owned = False
    if client is None:
        client = RapidixClient.from_settings(transport=transport)
        owned = True
    _ = owned

    external_series_id = source.get("external_series_id")
    if not external_series_id:
        raise RapidixError(
            "NOT_CONFIGURED",
            "Source has no external_series_id yet (search-to-source flow lands in Phase 2).",
        )

    # Resolve the series shell first (single episode_details call doubles
    # as a series probe when the provider lacks a dedicated endpoint).
    series_row, created_series = repo.upsert_series(
        source_id=source_id, provider=PROVIDER,
        external_series_id=external_series_id,
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
        except RapidixError:
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
