"""Facebook source scanner: paginated listing -> Turso inventory.

Modes:
- initial: walk cursors until END_OF_RESULTS (or safety cap). New sources only.
- incremental (manual default): stop after K consecutive pages with zero new
  videos (KNOWN_ITEMS_REACHED) — never on a single known video.
- full (manual explicit): like initial, resumable from the stored cursor.

Progress/checkpoint live in Turso (audio_scan_runs), so a restart resumes
from next_cursor instead of re-walking. One active run per source: a second
start returns the running run instead of duplicating work.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("backend-audio.scanner")

_tasks: dict[str, asyncio.Task] = {}


def scan_status(source_id: str) -> dict[str, Any] | None:
    from app.db.repositories import scan_runs

    run = scan_runs.active_run_for_source(source_id)
    if run is None:
        run = scan_runs.latest_run_for_source(source_id)
    if run is not None:
        return _public(run)
    return None


def _public(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": run["id"],
        "state": run["status"],
        "scan_mode": run.get("scan_mode"),
        "pages_fetched": run.get("pages_fetched") or 0,
        "found": run.get("videos_discovered") or 0,
        "added": run.get("videos_added") or 0,
        "skipped_known": run.get("videos_existing") or 0,
        "pagination_exhausted": bool(run.get("pagination_exhausted")),
        "stop_reason": run.get("stop_reason"),
        "error": run.get("last_error_message"),
        "error_code": run.get("last_error_code"),
    }


async def scan_source(source_id: str, *, full: bool = False,
                      limit: int = 5000) -> dict[str, Any]:
    """Queue (or attach to) a scan. Returns the run state immediately."""
    from app.db.client import get_client
    from app.db.repositories import scan_runs

    row = get_client().execute("SELECT * FROM audio_sources WHERE id = ?",
                               (source_id,)).fetchone()
    if row is None:
        raise ValueError("Source not found.")
    source = dict(row)

    active = scan_runs.active_run_for_source(source_id)
    if active is not None:
        return _public(active)

    if full:
        mode = "full"
    elif scan_runs.latest_run_for_source(source_id) is None:
        mode = "initial"
    else:
        mode = "incremental"
    run = scan_runs.create_run(source_id, source["pipeline_id"], mode)
    task = asyncio.create_task(_run_scan(run["id"], limit=limit))
    _tasks[run["id"]] = task
    task.add_done_callback(lambda t, rid=run["id"]: _tasks.pop(rid, None))
    return _public(run)


async def _run_scan(run_id: str, *, limit: int,
                    transport=None) -> None:
    from app.config import settings
    from app.db.repositories import scan_runs
    from app.db.repositories import sources as src_repo
    from app.services.facebook_listing import (
        END_OF_RESULTS,
        KNOWN_ITEMS_REACHED,
        SAFETY_LIMIT,
        ListingError,
        FacebookListingClient,
    )

    run = scan_runs.get_run(run_id)
    if run is None or run["status"] not in ("queued", "running"):
        return
    source_id = run["source_id"]
    mode = run.get("scan_mode") or "initial"

    from app.db.client import get_client

    src_row = get_client().execute("SELECT * FROM audio_sources WHERE id = ?",
                                   (source_id,)).fetchone()
    if src_row is None:
        scan_runs.update_run(run_id, status="failed",
                             last_error_code="SOURCE_GONE",
                             last_error_message="Source was deleted.",
                             completed_at=_now())
        return
    source = dict(src_row)
    if not source.get("enabled"):
        scan_runs.update_run(run_id, status="failed",
                             last_error_code="SOURCE_DISABLED",
                             last_error_message="Source is disabled.",
                             completed_at=_now())
        return

    scan_runs.update_run(run_id, status="running", started_at=_now())
    try:
        client = FacebookListingClient.from_settings(transport=transport)
    except ListingError as exc:
        scan_runs.update_run(run_id, status="failed",
                             last_error_code=exc.code,
                             last_error_message=str(exc)[:500],
                             completed_at=_now())
        return

    max_pages = int(settings.AUDIO_SCAN_MAX_PAGES or 200)
    max_videos = min(int(limit or 5000),
                     int(settings.AUDIO_SCAN_MAX_VIDEOS or 5000))
    known_stop = max(1, int(settings.AUDIO_SCAN_KNOWN_PAGES_STOP or 3))

    try:
        reels_page_id = await client.resolve_reels_page_id(
            source["canonical_url"] or source["url"])
    except ListingError as exc:
        scan_runs.update_run(run_id, status="failed",
                             last_error_code=exc.code,
                             last_error_message=str(exc)[:500],
                             completed_at=_now())
        return

    run = scan_runs.get_run(run_id) or run
    cursor = run.get("next_cursor")
    pages = run.get("pages_fetched") or 0
    discovered = run.get("videos_discovered") or 0
    added = run.get("videos_added") or 0
    existing = run.get("videos_existing") or 0
    seen_ids: set[str] = set()
    known_streak = 0
    stop_reason = END_OF_RESULTS

    while True:
        live = scan_runs.get_run(run_id)
        if live is None or live["status"] != "running":
            return  # paused/cancelled: cursor already persisted, resume later
        if pages >= max_pages or len(seen_ids) >= max_videos:
            stop_reason = SAFETY_LIMIT
            break
        try:
            page = await client.list_videos(
                source.get("page_id") or "", cursor=cursor,
                reels_page_id=reels_page_id)
        except ListingError as exc:
            scan_runs.update_run(
                run_id, status="failed", next_cursor=cursor,
                pages_fetched=pages, videos_discovered=discovered,
                videos_added=added, videos_existing=existing,
                last_error_code=exc.code,
                last_error_message=str(exc)[:500], completed_at=_now())
            return
        pages += 1
        new_this_page = 0
        for item in page.items:
            if item["video_id"] in seen_ids:
                continue
            seen_ids.add(item["video_id"])
            discovered += 1
            created = _persist_video(source, item)
            if created:
                added += 1
                new_this_page += 1
            else:
                existing += 1
        cursor = page.next_cursor if page.has_more else None
        scan_runs.update_run(
            run_id, next_cursor=cursor, pages_fetched=pages,
            videos_discovered=discovered, videos_added=added,
            videos_existing=existing)
        if mode == "incremental":
            known_streak = known_streak + 1 if new_this_page == 0 else 0
            if known_streak >= known_stop:
                stop_reason = KNOWN_ITEMS_REACHED
                break
        if not page.has_more:
            stop_reason = END_OF_RESULTS
            break

    exhausted = 1 if stop_reason == END_OF_RESULTS else 0
    scan_runs.update_run(
        run_id, status="completed" if stop_reason != SAFETY_LIMIT else "partial",
        next_cursor=cursor, pages_fetched=pages, videos_discovered=discovered,
        videos_added=added, videos_existing=existing,
        pagination_exhausted=exhausted, stop_reason=stop_reason,
        completed_at=_now())
    src_repo.touch_source_scanned(source_id)


def _persist_video(source: dict, item: dict) -> bool:
    """Persist one video; True when newly added. Never touches existing rows."""
    from app.db.repositories import sources as src_repo

    _, created = src_repo.upsert_inventory_item(
        source["pipeline_id"], source["id"], item["video_id"], item["url"],
        caption=item.get("caption"), thumbnail_url=item.get("thumbnail_url"),
        duration_seconds=item.get("duration_seconds"))
    return created


def _now() -> str:
    from app.db.repositories import now_iso

    return now_iso()


def pause_scan(source_id: str) -> None:
    from app.db.repositories import scan_runs

    active = scan_runs.active_run_for_source(source_id)
    if active is not None:
        scan_runs.update_run(active["id"], status="paused")
