"""TikTok scan service — Initial Scan, Auto Replenishment, dedup.

Uses the provider adapter from ``tiktok_provider_factory`` so the
Scheduler never depends on a concrete provider implementation.
"""

import logging
import time
from typing import Any

from ..config import settings
from ..db.repositories import reels, scan_runs, sources
from .tiktok_provider import ProviderError, ProfileNotFound, TikTokReel, TikTokProvider
from .tiktok_provider_factory import get_scan_provider
from .tiktok_url import extract_username, normalize_url

logger = logging.getLogger("backend-tiktok.services.scan")

SCAN_WRITE_CHUNK = settings.tiktok_scan_write_chunk or 100


async def scan_source(
    source_id: str,
    scan_run_id: str,
    scan_mode: str = "initial",
) -> dict[str, int]:
    """Scan a TikTok source for videos and insert new reels.

    Returns stats: {discovered, inserted, existing}.
    """
    source = await sources.get_source(source_id)
    if source is None:
        logger.warning("scan_source: source %s not found", source_id)
        return {"discovered": 0, "inserted": 0, "existing": 0}

    username = source["username"]
    provider: TikTokProvider = get_scan_provider()

    # Resolve profile (verify provider + get user_id)
    try:
        profile = await provider.resolve_profile(username)
    except ProfileNotFound as exc:
        await scan_runs.mark_scan_run_error(
            scan_run_id, f"Profile not found: {username}: {exc}"
        )
        await sources.update_scan_state(source_id, scan_status="failed", scan_error=str(exc))
        logger.error("scan_source: profile not found for @%s", username)
        return {"discovered": 0, "inserted": 0, "existing": 0}
    except ProviderError as exc:
        await scan_runs.mark_scan_run_error(scan_run_id, f"Provider error: {exc}")
        await sources.update_scan_state(
            source_id, scan_status="failed", scan_error=str(exc)
        )
        logger.warning("scan_source: provider error for @%s: %s", username, exc)
        return {"discovered": 0, "inserted": 0, "existing": 0}

    discovered = 0
    inserted = 0
    existing = 0
    cursor: str | None = None
    prev_cursor: str | None = None
    max_total = settings.tiktok_source_max_count

    while True:
        try:
            reels_batch, cursor = await provider.list_videos(
                profile, cursor=cursor, limit=min(SCAN_WRITE_CHUNK, max_total)
            )
        except ProviderError as exc:
            logger.warning("scan_source: list_videos error for @%s: %s", username, exc)
            await scan_runs.mark_scan_run_error(scan_run_id, f"List error: {exc}")
            break

        if not reels_batch:
            break

        # Detect non-advancing cursor (Source API may not support real
        # pagination).  If cursor is unchanged from the previous page, stop.
        if cursor is not None and cursor == prev_cursor:
            logger.info("scan_source: cursor not advancing, marking partial scan")
            break
        prev_cursor = cursor

        for reel in reels_batch:
            discovered += 1
            status, _, _ = await _insert_reel(source_id, reel)
            if status == "INSERTED":
                inserted += 1
            else:
                existing += 1

        # Respect configured max
        if discovered >= max_total:
            logger.info("scan_source: reached max_videos (%s), stopping", discovered)
            break
        if not cursor:
            break

    await scan_runs.complete_scan_run(
        scan_run_id,
        discovered_count=discovered,
        inserted_count=inserted,
        existing_count=existing,
        crawl_complete=(cursor is None),
        status="completed",
    )
    await sources.update_scan_state(
        source_id,
        scan_status="completed",
        discovered_total=discovered,
        initial_scan_completed=(scan_mode == "initial"),
        crawl_complete=(cursor is None),
    )

    logger.info(
        "scan_source: @%s %s — discovered=%d inserted=%d existing=%d",
        username, scan_mode, discovered, inserted, existing,
    )
    return {"discovered": discovered, "inserted": inserted, "existing": existing}


async def _insert_reel(source_id: str, reel: TikTokReel) -> tuple[str, Any, Any]:
    """Insert a reel with dedup by (source_id, reel_id)."""
    return await reels.insert_reel_if_new(
        source_id=source_id,
        reel_id=reel.video_id,
        reel_url=reel.video_url,
        caption=reel.caption,
        thumbnail_url=reel.thumbnail_url,
        source_published_at=_format_create_time(reel.create_time),
        duration=reel.duration,
        play_count=reel.play_count,
    )


def _format_create_time(ts: int | None) -> str | None:
    if ts is None:
        return None
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
    except (ValueError, TypeError):
        return None
