import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import yt_dlp
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.inventory import sync_source_inventory
from app.models import DouyinSource, Pipeline

logger = logging.getLogger("douyin-youtube-monitor")

monitor_runtime: dict[str, Any] = {
    "last_cycle_started_at": None,
    "last_cycle_finished_at": None,
    "last_cycle_ok": True,
    "consecutive_failures": 0,
    "last_error": None,
    "last_replenish_count": 0,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def extract_video_id_from_url(url: str | None) -> str | None:
    if not url:
        return None

    match = re.search(r'/video/(\d+)', url)
    if match:
        return match.group(1)

    match = re.search(r'v\.douyin\.com/([a-zA-Z0-9]+)', url)
    if match:
        return match.group(1)

    return None


def fetch_latest_videos_from_source(
    profile_url: str,
    source_id: str,
) -> list[dict[str, Any]]:
    if not profile_url:
        return []

    yt_dlp_options = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "playlistend": 10,
        "socket_timeout": 30,
        "retries": 2,
        "fragment_retries": 2,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/18.0 Mobile/15E148 Safari/604.1"
            ),
        },
    }

    videos: list[dict[str, Any]] = []

    try:
        with yt_dlp.YoutubeDL(yt_dlp_options) as ydl:
            info = ydl.extract_info(
                profile_url,
                download=False,
            )

            if info is None:
                return videos

            entries = info.get("entries") or []
            if not entries and info.get("_type") == "video":
                entries = [info]

            for entry in entries:
                if not isinstance(entry, dict):
                    continue

                video_url = entry.get("url") or entry.get("webpage_url") or entry.get("original_url")
                video_id = (
                    extract_video_id_from_url(video_url)
                    or entry.get("id")
                    or entry.get("display_id")
                )

                if not video_id:
                    continue

                title = str(entry.get("title") or entry.get("description") or "").strip()
                description = str(entry.get("description") or "").strip()

                videos.append({
                    "video_id": str(video_id),
                    "title": title[:200],
                    "description": description[:1000],
                    "url": str(video_url or profile_url),
                })

    except Exception as exc:
        logger.warning(
            "Failed to fetch videos from source=%s profile=%s: %s",
            source_id,
            profile_url,
            exc,
        )

    return videos


def _build_source_context(profile_url: str, videos: list[dict[str, Any]]) -> str:
    parts = [f"profile_url: {profile_url}"]

    for video in videos[:5]:
        title = video.get("title", "")
        desc = video.get("description", "")
        if title:
            parts.append(f"video_title: {title}")
        if desc:
            parts.append(f"video_description: {desc}")

    return "\n".join(parts)[:6000]


def _platform_account_ok(platform: str) -> bool:
    if platform != "douyin":
        return True  # Facebook stub always ok for now
    try:
        from app.models import PlatformAccount

        with SessionLocal() as _db:
            acct = _db.execute(select(PlatformAccount).where(PlatformAccount.platform == "douyin").limit(1)).scalar_one_or_none()
            if acct is None:
                return False
            if acct.status != "connected" or getattr(acct, "needs_reauth", False):
                return False
        return True
    except Exception:
        return False


def _source_is_due(source: DouyinSource, now: datetime) -> bool:
    if not source.enabled:
        return False
    platform = getattr(source, "platform", "douyin") or "douyin"
    if platform == "douyin" and not _platform_account_ok("douyin"):
        return False
    nxt = source.next_scan_at
    if nxt is not None:
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=timezone.utc)
        if nxt > now:
            return False
    return True


def _scan_one_source(source_id: str) -> None:
    # Manual-inventory mode: Douyin discovery is admin-driven only. The
    # scheduler reads Inventory; it never spends a RapidAPI request.
    if not getattr(settings, "douyin_auto_scan_enabled", False):
        logger.info("Douyin auto-scan disabled; skipping source=%s", source_id)
        return
    _scan_one_source_impl(source_id)


def _scan_one_source_impl(source_id: str) -> None:
    try:
        with SessionLocal() as db:
            source = db.get(DouyinSource, source_id)
            if source is None or not source.enabled:
                return
            platform = getattr(source, "platform", "douyin") or "douyin"
            if platform == "douyin" and not _platform_account_ok("douyin"):
                logger.info("Skipping source %s: Douyin PlatformAccount not ready", source_id)
                return
            pipeline_id = source.pipeline_id
            profile_url = source.profile_url or ""
            user_id = source.douyin_sec_uid or source.douyin_user_id or ""
            if user_id and not profile_url:
                profile_url = f"https://www.douyin.com/user/{user_id}"
            if not profile_url:
                logger.info("Source %s has no profile_url, skipping", source.id)
                return
            pipeline = (
                db.get(Pipeline, pipeline_id) if pipeline_id else None
            )
            if pipeline is None or not pipeline.enabled:
                return
            logger.info(
                "Checking source=%s pipeline=%s profile=%s",
                source.id, pipeline.id, profile_url,
            )
    except Exception:
        logger.exception("Failed to pre-check source=%s", source_id)
        return
    try:
        # Continuous monitor: latest pages only with early stop.
        # Initial full scans happen on source creation / manual Sync.
        sync_source_inventory(source_id, mode="latest")
    except Exception:
        logger.exception("Failed to process source=%s", source_id)


def count_available_inventory_for_source(db: Session, source_id: str) -> int:
    """Number of unposted videos in pickable statuses for this source."""
    from sqlalchemy import func
    from app.models import DouyinVideo
    from app.scheduler import PICKABLE_VIDEO_STATUSES

    count = db.execute(
        select(func.count(DouyinVideo.id))
        .where(DouyinVideo.source_id == source_id)
        .where(DouyinVideo.status.in_(PICKABLE_VIDEO_STATUSES))
    ).scalar_one_or_none()
    return int(count or 0)


def check_and_schedule_replenishments(db: Session) -> list[str]:
    """Evaluate sources for auto-replenishment when inventory is low or stale."""
    if not getattr(settings, "douyin_auto_replenish_enabled", True):
        return []

    from app import douyin_import
    from app.models import DouyinScanJob

    now = utcnow()
    threshold = int(getattr(settings, "douyin_replenish_threshold", 3) or 3)
    min_interval_hours = float(getattr(settings, "douyin_refresh_min_interval_hours", 6.0) or 6.0)
    periodic_days = float(getattr(settings, "douyin_periodic_refresh_days", 7.0) or 7.0)

    sources = db.execute(
        select(DouyinSource)
        .where(DouyinSource.enabled == True)  # noqa: E712
    ).scalars().all()

    scheduled: list[str] = []
    sources_updated = False
    for source in sources:
        pipeline = db.get(Pipeline, source.pipeline_id) if source.pipeline_id else None
        if pipeline is None or not pipeline.enabled:
            continue

        # Check quota/provider gate per source (does not block self-hosted)
        if not douyin_import.can_start_import(source=source):
            continue

        # Check if an active scan job already exists
        has_active_job = db.execute(
            select(DouyinScanJob.id)
            .where(DouyinScanJob.source_id == source.id)
            .where(DouyinScanJob.status.in_(["pending", "running"]))
            .limit(1)
        ).scalar_one_or_none()
        if has_active_job:
            continue

        # Cooldown check
        last_scan = source.last_scan_at or source.last_refresh_at
        is_failed = (source.inventory_sync_status == "failed" or source.provider_status != "ok")
        if last_scan is not None:
            if last_scan.tzinfo is None:
                last_scan = last_scan.replace(tzinfo=timezone.utc)
            if is_failed:
                eff_next = source.next_scan_at or (last_scan + timedelta(minutes=5))
                if eff_next.tzinfo is None:
                    eff_next = eff_next.replace(tzinfo=timezone.utc)
                if now < eff_next:
                    continue
            else:
                eff_next = last_scan + timedelta(hours=min_interval_hours)
                if source.next_scan_at != eff_next:
                    source.next_scan_at = eff_next
                    sources_updated = True
                elapsed_hours = (now - last_scan).total_seconds() / 3600.0
                if elapsed_hours < min_interval_hours:
                    continue

        available = count_available_inventory_for_source(db, source.id)
        should_replenish = False
        reason = ""

        if available <= threshold:
            should_replenish = True
            reason = f"LOW_INVENTORY (available={available} <= {threshold})"
        elif last_scan is not None:
            elapsed_days = (now - last_scan).total_seconds() / 86400.0
            if elapsed_days >= periodic_days:
                should_replenish = True
                reason = f"PERIODIC_REFRESH ({elapsed_days:.1f} days >= {periodic_days} days)"

        if should_replenish:
            logger.info("Scheduling replenish scan for source %s: %s", source.id, reason)
            job = douyin_import.queue_scan_job(db, source.id, scan_mode="replenish")
            source.next_scan_at = now
            sources_updated = True
            scheduled.append(job.id)

    if sources_updated:
        try:
            db.commit()
        except Exception:
            db.rollback()

    return scheduled


def run_monitor_once() -> None:
    """Monitor cycle: handles auto-replenishment, scan jobs execution, and legacy auto-scan."""
    from app import douyin_import

    now = utcnow()
    monitor_runtime["last_cycle_started_at"] = now.isoformat()

    try:
        # 0. Crash recovery: release stale locked scan jobs if any crashed worker left them
        with SessionLocal() as db:
            try:
                douyin_import.recover_incomplete_scan_jobs(db, max_age_seconds=1800)
            except Exception:
                logger.exception("Failed recovering incomplete scan jobs")

        # 1. Evaluate auto-replenishment
        scheduled_count = 0
        with SessionLocal() as db:
            try:
                scheduled_ids = check_and_schedule_replenishments(db)
                scheduled_count = len(scheduled_ids)
                if scheduled_ids:
                    logger.info("Scheduled %s replenishment scan job(s)", scheduled_count)
            except Exception:
                logger.exception("Failed checking auto-replenishments")

        monitor_runtime["last_replenish_count"] = scheduled_count

        # 2. Claim and run pending scan jobs up to max concurrency
        max_concurrent = max(1, int(getattr(settings, "douyin_scan_max_concurrent_sources", 1) or 1))
        for _ in range(max_concurrent):
            try:
                summary = douyin_import.claim_and_run_scan_job(worker_id="monitor_worker")
                if summary is None:
                    break
                logger.info("Executed scan job from queue: %s", summary)
            except Exception:
                logger.exception("Failed executing queued scan job")
                break

        # 3. Legacy auto-scan if enabled
        if getattr(settings, "douyin_auto_scan_enabled", False):
            now_scan = utcnow()
            with SessionLocal() as db:
                sources = db.execute(
                    select(DouyinSource)
                    .where(DouyinSource.enabled == True)  # noqa: E712
                    .order_by(DouyinSource.created_at.asc())
                ).scalars().all()
                due_ids = [s.id for s in sources if _source_is_due(s, now_scan)]

            try:
                concurrency = int(
                    getattr(settings, "douyin_scan_concurrency", 2) or 2
                )
            except (TypeError, ValueError):
                concurrency = 2
            concurrency = max(1, min(concurrency, 4))

            if due_ids:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=concurrency
                ) as pool:
                    futures = [pool.submit(_scan_one_source, sid) for sid in due_ids]
                    for fut in concurrent.futures.as_completed(futures):
                        try:
                            fut.result()
                        except Exception:
                            logger.exception("Monitor scan task failed")

        monitor_runtime["last_cycle_finished_at"] = utcnow().isoformat()
        monitor_runtime["last_cycle_ok"] = True
        monitor_runtime["consecutive_failures"] = 0
        monitor_runtime["last_error"] = None
    except Exception as exc:
        monitor_runtime["last_cycle_finished_at"] = utcnow().isoformat()
        monitor_runtime["last_cycle_ok"] = False
        monitor_runtime["consecutive_failures"] = int(monitor_runtime.get("consecutive_failures", 0)) + 1
        monitor_runtime["last_error"] = str(exc)[:500]
        raise


async def monitor_loop() -> None:
    if not getattr(settings, "monitor_enabled", True):
        logger.info("Douyin source monitor is disabled")
        return

    startup_delay = getattr(settings, "monitor_startup_delay_seconds", 10)
    poll_interval = getattr(settings, "monitor_poll_seconds", 300)

    logger.info("Douyin source monitor started, waiting %s seconds before first run", startup_delay)
    await asyncio.sleep(startup_delay)

    while True:
        try:
            logger.info("Starting monitor cycle")
            await asyncio.to_thread(run_monitor_once)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Monitor loop error")

        logger.info("Monitor sleeping for %s seconds", poll_interval)
        await asyncio.sleep(poll_interval)
