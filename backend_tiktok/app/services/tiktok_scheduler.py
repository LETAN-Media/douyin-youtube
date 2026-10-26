"""Daily batch scheduler for the TikTok → YouTube pipeline.

Implements automated daily batch planning:
1. Verifies Pipeline status (enabled, auto_publish).
2. Verifies YouTube Destination connectivity and authorization.
3. Checks daily publication quota and active schedule slots.
4. Filters eligible unpublished videos from TikTok inventory according to format (Shorts / Regular / Both).
5. Generates AI metadata according to Pipeline AI Settings.
6. Enqueues publication jobs into ``tiktok_publish_queue`` and ``tiktok_publications``.
7. Allows manual execution ("run batch now") without waiting for the batch hour.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any

from ..config import settings
from ..db.client import execute, result_to_dict, result_to_dicts
from ..db.repositories import (
    destinations,
    pipelines,
    publications,
    publish_queue,
    reels,
    scan_runs,
    schedules,
    sources,
)
from . import schedule_generator, tiktok_scan
from .tiktok_ai_metadata import generate_ai_metadata

logger = logging.getLogger("backend-tiktok.services.scheduler")

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"
_DEFAULT_BATCH_TIME = "06:00"
_DEFAULT_MAX_DAILY = 5


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_time(value: str) -> tuple[int, int]:
    m = _TIME_RE.match(value.strip())
    if not m:
        return 6, 0
    return int(m.group(1)), int(m.group(2))


def _slot_to_utc_rfc3339(date_iso: str, slot_time: str, tz_name: str) -> str:
    year, month, day = (int(p) for p in date_iso.split("-"))
    hour, minute = _parse_time(slot_time)
    tz = ZoneInfo(tz_name)
    local_dt = datetime(year, month, day, hour, minute, tzinfo=tz)
    return local_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def scheduler_loop(stop_event: asyncio.Event) -> None:
    """Background scheduler: poll for due source scans and due publication batches."""
    logger.info("TikTok scheduler started (batch_time=%s)", settings.tiktok_scheduler_batch_time)
    poll_seconds = max(settings.tiktok_scheduler_poll_seconds, 10)

    while not stop_event.is_set():
        try:
            await _run_due_scans()
        except Exception as exc:
            logger.exception("scheduler_loop error in scans: %s", exc)

        try:
            await _run_due_schedules()
        except Exception as exc:
            logger.exception("scheduler_loop error in schedules: %s", exc)

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
            existing = await _active_scan(src["id"])
            if existing:
                continue
            scan_run_id = f"scan_{secrets.token_hex(8)}"
            await scan_runs.create_scan_run(
                scan_run_id, src["id"], scan_mode="incremental"
            )
            asyncio.create_task(_scan_and_cleanup(src["id"], scan_run_id))


async def _active_scan(source_id: str) -> bool:
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


async def _run_due_schedules() -> None:
    """Check each enabled pipeline with auto_publish=1 and execute daily batch when due."""
    pipeline_rows = await pipelines.list_pipelines()
    for p in pipeline_rows:
        if not p.get("enabled") or not p.get("auto_publish"):
            continue
        pipeline_id = p["id"]
        try:
            await execute_daily_batch(pipeline_id, force_now=False)
        except Exception as exc:
            logger.exception("Failed to execute daily batch for pipeline %s: %s", pipeline_id, exc)


async def execute_daily_batch(
    pipeline_id: str,
    destination_id: str | None = None,
    *,
    force_now: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Plan and enqueue publication jobs for a pipeline's daily batch.

    Args:
        pipeline_id: ID of the TikTok pipeline.
        destination_id: Optional specific YouTube destination ID. If None, resolves default/active.
        force_now: If True (e.g. user clicked 'Run Batch Now'), bypasses batch_time & day check.
        now: Optional custom reference timestamp (used for testing).
    """
    pipeline = await pipelines.get_pipeline(pipeline_id)
    if pipeline is None:
        return {"ok": False, "reason": "PIPELINE_NOT_FOUND", "message": "Pipeline không tồn tại."}

    if not force_now and (not pipeline.get("enabled") or not pipeline.get("auto_publish")):
        return {
            "ok": False,
            "reason": "AUTO_PUBLISH_DISABLED",
            "message": "Auto Publish đang tắt cho Pipeline này.",
        }

    # Resolve target YouTube destination
    dest = None
    if destination_id:
        dest = await destinations.get_destination(destination_id)
    else:
        dest = await destinations.get_default_destination(pipeline_id)
        if not dest:
            dest_list = await destinations.list_destinations(pipeline_id)
            connected = [d for d in dest_list if d.get("connected") and d.get("enabled")]
            if connected:
                dest = connected[0]

    if not dest or not dest.get("connected") or not dest.get("enabled"):
        return {
            "ok": False,
            "reason": "NO_DESTINATION",
            "message": "Chưa có kênh YouTube nào được kích hoạt và liên kết cho Pipeline này.",
        }
    resolved_destination_id = dest["id"]

    # Check Quota pause
    utc_now = now or datetime.now(timezone.utc)
    if utc_now.tzinfo is None:
        utc_now = utc_now.replace(tzinfo=timezone.utc)
    now_iso = utc_now.strftime("%Y-%m-%dT%H:%M:%SZ")

    quota_res = await execute(
        "SELECT paused_until, reason FROM tiktok_quota_pauses WHERE pipeline_id = :pid AND paused_until > :now",
        {"pid": pipeline_id, "now": now_iso},
    )
    if quota_res.rows:
        return {
            "ok": False,
            "reason": "QUOTA_PAUSED",
            "message": f"YouTube đang tạm dừng do giới hạn quota (đến {quota_res.rows[0][0]}).",
        }

    # Schedule configuration
    schedule = await schedules.get_by_pipeline(pipeline_id)
    if not schedule:
        schedule = await schedules.get_or_create_schedule(pipeline_id)

    if not force_now and not schedule.get("enabled"):
        return {
            "ok": False,
            "reason": "SCHEDULE_DISABLED",
            "message": "Lịch đăng tự động (Schedule) đang tắt cho Pipeline này.",
        }

    tz_name = schedule.get("timezone") or _DEFAULT_TIMEZONE
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo(_DEFAULT_TIMEZONE)

    now_local = utc_now.astimezone(tz)
    local_date = now_local.date().isoformat()
    weekday = now_local.weekday()

    # Active days check
    active_days = schedule.get("active_days") or [0, 1, 2, 3, 4, 5, 6]
    if not force_now and weekday not in active_days:
        return {
            "ok": False,
            "reason": "DAY_NOT_ACTIVE",
            "message": f"Hôm nay ({now_local.strftime('%A')}) không thuộc ngày đăng theo lịch.",
        }

    # Batch time check
    batch_time = schedule.get("batch_time") or _DEFAULT_BATCH_TIME
    if not force_now:
        bh, bm = _parse_time(batch_time)
        batch_dt = now_local.replace(hour=bh, minute=bm, second=0, microsecond=0)
        if now_local < batch_dt:
            return {
                "ok": False,
                "reason": "NOT_BEFORE_BATCH_TIME",
                "message": f"Chưa tới giờ chạy lịch hôm nay ({batch_time}).",
            }

    # Daily limit & counting already published/scheduled today
    max_daily = max(1, min(10, int(schedule.get("max_daily_publish") or _DEFAULT_MAX_DAILY)))

    start_local = datetime(now_local.year, now_local.month, now_local.day, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_utc = end_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    count_res = await execute(
        """
        SELECT COUNT(*) as cnt FROM tiktok_publications
        WHERE destination_id = :did
        AND (
            (scheduled_publish_at >= :start AND scheduled_publish_at < :end)
            OR (published_at >= :start AND published_at < :end)
        )
        AND status IN ('queued', 'processing', 'scheduled', 'published')
        """,
        {"did": resolved_destination_id, "start": start_utc, "end": end_utc},
    )
    already_count = count_res.rows[0][0] if count_res.rows else 0
    remaining_quota = max(0, max_daily - already_count)

    if remaining_quota <= 0:
        return {
            "ok": False,
            "reason": "DAILY_LIMIT_REACHED",
            "message": f"Đã đạt giới hạn tối đa {max_daily} video/ngày hôm nay ({already_count} video đã lên lịch/đăng).",
            "daily_limit": max_daily,
            "already_count": already_count,
        }

    # Retrieve or generate schedule slots
    slot_rows = await schedules.list_slots(schedule["id"])
    today_enabled_slots = [
        s for s in slot_rows if s.get("weekday") == weekday and s.get("enabled")
    ]

    # If no slots enabled for this weekday, generate default week slots
    if not today_enabled_slots:
        await schedule_generator.generate_week_schedule(
            pipeline_id, max_daily=max_daily, batch_time=batch_time
        )
        slot_rows = await schedules.list_slots(schedule["id"])
        today_enabled_slots = [
            s for s in slot_rows if s.get("weekday") == weekday and s.get("enabled")
        ]

    # Collect available future slots
    open_slots: list[tuple[str, str]] = []  # (slot_time_str, slot_utc_iso)
    for s in sorted(today_enabled_slots, key=lambda x: x.get("slot_time", "")):
        st = s.get("slot_time", "")
        sh, sm = _parse_time(st)
        slot_dt = now_local.replace(hour=sh, minute=sm, second=0, microsecond=0)

        # In automatic mode, slots must be in the future
        if not force_now and slot_dt <= now_local:
            continue

        slot_utc = slot_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Check if slot is already occupied
        occupied_res = await execute(
            """
            SELECT 1 FROM tiktok_publications
            WHERE destination_id = :did AND scheduled_publish_at = :utc
            AND status IN ('queued', 'processing', 'scheduled', 'published')
            LIMIT 1
            """,
            {"did": resolved_destination_id, "utc": slot_utc},
        )
        if not occupied_res.rows:
            open_slots.append((st, slot_utc))

    # If force_now and no future slots remain today, allocate upcoming incremental slots
    if force_now and not open_slots:
        min_int = max(5, int(schedule.get("min_interval_minutes") or 60))
        for i in range(remaining_quota):
            f_dt = now_local + timedelta(minutes=min_int * (i + 1))
            st = f_dt.strftime("%H:%M")
            f_utc = f_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            open_slots.append((st, f_utc))

    slots_to_allocate = open_slots[:remaining_quota]
    if not slots_to_allocate:
        return {
            "ok": False,
            "reason": "NO_FUTURE_SLOTS",
            "message": "Không còn khung giờ phát hành trống nào trong ngày hôm nay.",
            "remaining_quota": remaining_quota,
        }

    # Query eligible unpublished videos from Inventory
    video_order = (schedule.get("video_order") or "newest").lower()
    order_clause = (
        "r.source_published_at DESC, r.discovered_at DESC, r.id DESC"
        if video_order == "newest"
        else "r.source_published_at ASC, r.discovered_at ASC, r.id ASC"
    )

    fetch_limit = len(slots_to_allocate) * 3
    reels_res = await execute(
        f"""
        SELECT r.id, r.source_id, r.reel_id, r.reel_url, r.caption,
               r.thumbnail_url, r.duration, r.source_published_at
        FROM tiktok_reels r
        JOIN tiktok_sources s ON s.id = r.source_id
        WHERE s.pipeline_id = :pid
        AND s.enabled = 1
        AND r.status IN ('new', 'active')
        AND NOT EXISTS (
            SELECT 1 FROM tiktok_publications pub
            WHERE pub.reel_db_id = r.id AND pub.destination_id = :did
            AND pub.status IN ('queued', 'processing', 'scheduled', 'published')
        )
        ORDER BY {order_clause}
        LIMIT :limit
        """,
        {"pid": pipeline_id, "did": resolved_destination_id, "limit": fetch_limit},
    )
    candidate_reels = result_to_dicts(reels_res)

    # Filter according to youtube_upload_mode
    upload_mode = pipeline.get("youtube_upload_mode") or "shorts"
    eligible_reels: list[dict[str, Any]] = []
    for r in candidate_reels:
        dur = r.get("duration")
        if upload_mode == "shorts" and dur and dur > 180:
            continue
        eligible_reels.append(r)
        if len(eligible_reels) >= len(slots_to_allocate):
            break

    if not eligible_reels:
        return {
            "ok": False,
            "reason": "NO_ELIGIBLE_INVENTORY",
            "message": f"Không có video phù hợp trong kho (cần định dạng '{upload_mode}').",
            "slots_available": len(slots_to_allocate),
        }

    # Create publication jobs and queue entries
    enqueued_jobs = []
    for i, reel_item in enumerate(eligible_reels[: len(slots_to_allocate)]):
        slot_label, slot_utc = slots_to_allocate[i]
        reel_db_id = reel_item["id"]

        # Pre-enrich AI metadata if configured
        ai_title = None
        ai_desc = None
        ai_hashtags = "[]"
        ai_model = None

        if settings.toolnet_ai_enabled and settings.toolnet_api_key:
            try:
                ai_meta = await generate_ai_metadata(
                    None, reel_item, reel_item.get("caption")
                )
                if ai_meta:
                    ai_title = ai_meta.get("title")
                    ai_desc = ai_meta.get("description")
                    ai_hashtags = ai_meta.get("hashtags_json") or "[]"
                    ai_model = ai_meta.get("model")
            except Exception as exc:
                logger.warning("AI generation during schedule failed: %s", exc)

        pub_id = f"pub_{secrets.token_hex(8)}"
        await publications.create_publication(
            publication_id=pub_id,
            reel_db_id=reel_db_id,
            destination_id=resolved_destination_id,
            status="queued",
            scheduled_publish_at=slot_utc,
            youtube_upload_mode=upload_mode,
            youtube_title=ai_title,
            youtube_description=ai_desc,
            youtube_hashtags_json=ai_hashtags,
            ai_model=ai_model,
        )

        job_id = f"job_{secrets.token_hex(8)}"
        await publish_queue.enqueue_publication_job(
            job_id=job_id,
            pipeline_id=pipeline_id,
            destination_id=resolved_destination_id,
            reel_db_id=reel_db_id,
            publication_id=pub_id,
            priority=100,
            stage="scheduled",
            scheduled_at=slot_utc,
        )

        await reels.advance_status(reel_db_id, "new", "scheduled")
        enqueued_jobs.append({
            "job_id": job_id,
            "publication_id": pub_id,
            "reel_id": reel_item.get("reel_id"),
            "slot_time": slot_label,
            "scheduled_at": slot_utc,
        })

    # Record batch execution in tiktok_scheduler_batches
    batch_id = f"batch_{secrets.token_hex(6)}"
    try:
        await schedules.create_batch(
            batch_id=batch_id,
            pipeline_id=pipeline_id,
            destination_id=resolved_destination_id,
            local_date=local_date,
            scheduled_batch_time=batch_time,
            planned_count=len(enqueued_jobs),
        )
    except Exception:
        # Ignore if duplicate batch row for today exists
        pass

    logger.info(
        "Scheduler enqueued %d video(s) for pipeline %s (destination %s)",
        len(enqueued_jobs),
        pipeline_id,
        resolved_destination_id,
    )

    return {
        "ok": True,
        "videos_enqueued": len(enqueued_jobs),
        "slots": enqueued_jobs,
        "date": local_date,
        "daily_limit": max_daily,
        "remaining_today": max(0, remaining_quota - len(enqueued_jobs)),
        "message": f"Đã lên lịch thành công {len(enqueued_jobs)} video vào hàng đợi.",
    }
