"""Daily batch scheduler for the TikTok → YouTube pipeline.

Depends on the ``TikTokProvider`` ABC via ``tiktok_provider_factory`` —
never on a concrete provider.  Swapping the TikTok Source API → another
adapter requires zero Scheduler changes.
"""

import asyncio
import logging
import secrets
import time
from datetime import datetime, timezone

from ..config import settings
from ..db.repositories import pipelines, scan_runs, sources
from . import tiktok_scan

logger = logging.getLogger("backend-tiktok.services.scheduler")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _should_run_batch(now: datetime, batch_time: str) -> bool:
    """Check if current time matches the configured batch_time (HH:MM)."""
    parts = batch_time.split(":")
    if len(parts) != 2:
        return False
    hour = int(parts[0])
    minute = int(parts[1])
    return now.hour == hour and now.minute == minute and now.second < 30


async def scheduler_loop(stop_event: asyncio.Event) -> None:
    """Background scheduler: poll for due scan runs, execute them."""
    logger.info("TikTok scheduler started (batch_time=%s)", settings.tiktok_scheduler_batch_time)
    poll_seconds = settings.tiktok_scheduler_poll_seconds

    while not stop_event.is_set():
        try:
            await _run_due_scans()
        except Exception as exc:
            logger.exception("scheduler_loop error: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
            break
        except asyncio.TimeoutError:
            continue

    logger.info("TikTok scheduler stopped")


async def _run_due_scans() -> None:
    """Scan all sources in all enabled pipelines."""
    pipeline_rows = await pipelines.list_pipelines()
    for p in pipeline_rows:
        if not p.get("enabled") or not p.get("auto_publish"):
            continue
        pipeline_id = p["id"]
        src_rows = await sources.list_sources(pipeline_id)
        for src in src_rows:
            if not src.get("enabled"):
                continue
            # Skip if a scan is already running for this source
            existing = await _active_scan(src["id"])
            if existing:
                continue
            scan_run_id = f"scan_{secrets.token_hex(8)}"
            await scan_runs.create_scan_run(
                scan_run_id, src["id"], scan_mode="incremental"
            )
            asyncio.create_task(_scan_and_cleanup(src["id"], scan_run_id))


async def _active_scan(source_id: str) -> bool:
    from ..db.client import execute

    res = await execute(
        "SELECT COUNT(*) as cnt FROM tiktok_scan_runs "
        "WHERE source_id = :sid AND status = 'running'",
        {"sid": source_id},
    )
    return (res.rows[0][0] > 0) if res.rows else False


async def _scan_and_cleanup(source_id: str, scan_run_id: str) -> None:
    try:
        await tiktok_scan.scan_source(source_id, scan_run_id, scan_mode="incremental")
    except Exception as exc:
        logger.exception("scan %s failed: %s", scan_run_id, exc)
        await scan_runs.mark_scan_run_error(scan_run_id, str(exc))
