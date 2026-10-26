"""Daily batch scheduler for the TikTok → YouTube pipeline.

Implements automated daily batch planning:
1. Verifies Pipeline status (enabled, auto_publish).
2. Verifies YouTube Destination connectivity and authorization.
3. Checks daily publication quota and active schedule slots (with HH:MM support).
4. Handles same-day and lookahead scheduling for upcoming active days when today's slots have passed.
5. Filters eligible unpublished videos from TikTok inventory according to format (Shorts / Regular / Both).
6. Generates AI metadata according to Pipeline AI Settings.
7. Enqueues publication jobs into ``tiktok_publish_queue`` and ``tiktok_publications``.
8. Supports dry-run Preview and on-demand "Run Batch Now" with limit constraints.
9. Tracks scheduler worker heartbeat and operational status.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
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
    system_state,
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
        # Heartbeat update
        try:
            await system_state.set_json(
                "worker:scheduler",
                {
                    "status": "idle",
                    "last_heartbeat": _now_iso(),
                    "service": settings.service_name,
                },
            )
        except Exception:
            pass

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


async def count_published_or_scheduled_for_date(
    destination_id: str,
    target_date: Any,
    tz: ZoneInfo,
) -> int:
    """Count publications already scheduled or published on a given local calendar date."""
    start_local = datetime(target_date.year, target_date.month, target_date.day, tzinfo=tz)
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
        {"did": destination_id, "start": start_utc, "end": end_utc},
    )
    return count_res.rows[0][0] if count_res.rows else 0


async def calculate_schedule_plan(
    pipeline_id: str,
    destination_id: str | None = None,
    *,
    force_now: bool = False,
    now: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Calculate batch scheduling plan for today or lookahead to next active day.

    In dry_run mode, returns planned slots and candidate videos without modifying DB.
    In execution mode, enqueues publications and jobs up to daily limit.
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
    today_date = now_local.date()
    today_weekday = today_date.weekday()
    batch_time = schedule.get("batch_time") or _DEFAULT_BATCH_TIME
    max_daily = max(1, min(10, int(schedule.get("max_daily_publish") or _DEFAULT_MAX_DAILY)))
    active_days = schedule.get("active_days") or [0, 1, 2, 3, 4, 5, 6]

    # Ensure slot records exist
    slot_rows = await schedules.list_slots(schedule["id"])
    enabled_slots = [s for s in slot_rows if s.get("enabled")]
    if not enabled_slots:
        await schedule_generator.generate_week_schedule(
            pipeline_id, max_daily=max_daily, batch_time=batch_time
        )
        slot_rows = await schedules.list_slots(schedule["id"])
        enabled_slots = [s for s in slot_rows if s.get("enabled")]

    bh, bm = _parse_time(batch_time)
    today_batch_dt = now_local.replace(hour=bh, minute=bm, second=0, microsecond=0)

    target_date = None
    target_slots: list[tuple[str, str, datetime]] = []
    is_lookahead = False

    # Check whether TODAY has open slots
    already_today = await count_published_or_scheduled_for_date(resolved_destination_id, today_date, tz)
    remaining_today = max(0, max_daily - already_today)

    # If today is an active day and already reached daily limit, stop and report DAILY_LIMIT_REACHED
    if today_weekday in active_days and remaining_today <= 0:
        return {
            "ok": False,
            "reason": "DAILY_LIMIT_REACHED",
            "message": f"Đã đạt giới hạn tối đa {max_daily} video/ngày hôm nay ({already_today} video đã lên lịch/đăng).",
            "daily_limit": max_daily,
            "already_count": already_today,
            "target_date": today_date.isoformat(),
        }

    can_schedule_today = False
    if today_weekday in active_days:
        if force_now or now_local >= today_batch_dt:
            can_schedule_today = True

    if can_schedule_today and remaining_today > 0:
        today_day_slots = sorted(
            [s for s in enabled_slots if s.get("weekday") == today_weekday],
            key=lambda x: x.get("slot_time", ""),
        )
        for s in today_day_slots:
            st = s.get("slot_time", "")
            sh, sm = _parse_time(st)
            slot_dt = now_local.replace(hour=sh, minute=sm, second=0, microsecond=0)

            # In automatic mode, slots must be in future or within a 15-minute grace period
            if not force_now and slot_dt < now_local - timedelta(minutes=15):
                continue

            effective_dt = slot_dt if slot_dt >= now_local else (now_local + timedelta(minutes=2))
            slot_utc = effective_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            occupied = await execute(
                """
                SELECT 1 FROM tiktok_publications
                WHERE destination_id = :did AND scheduled_publish_at = :utc
                AND status IN ('queued', 'processing', 'scheduled', 'published')
                LIMIT 1
                """,
                {"did": resolved_destination_id, "utc": slot_utc},
            )
            if not occupied.rows:
                target_slots.append((st, slot_utc, effective_dt))

        if target_slots:
            target_date = today_date
            target_slots = target_slots[:remaining_today]

    # If today has not reached batch time yet on an active day and not force_now, wait for batch hour
    if not target_slots and not force_now and today_weekday in active_days and now_local < today_batch_dt:
        return {
            "ok": False,
            "reason": "NOT_BEFORE_BATCH_TIME",
            "message": f"Chưa tới giờ chạy batch {batch_time} hôm nay (Múi giờ {tz_name}).",
            "batch_time": batch_time,
            "timezone": tz_name,
            "target_date": today_date.isoformat(),
        }

    # If today has no open slots remaining, LOOK AHEAD to next active days (up to 7 days ahead)
    if not target_slots:
        for day_offset in range(1, 8):
            cand_dt = now_local + timedelta(days=day_offset)
            cand_date = cand_dt.date()
            cand_wd = cand_date.weekday()
            if cand_wd not in active_days:
                continue

            cand_already = await count_published_or_scheduled_for_date(resolved_destination_id, cand_date, tz)
            cand_remaining = max(0, max_daily - cand_already)
            if cand_remaining <= 0:
                continue

            cand_day_slots = sorted(
                [s for s in enabled_slots if s.get("weekday") == cand_wd],
                key=lambda x: x.get("slot_time", ""),
            )
            cand_open_slots: list[tuple[str, str, datetime]] = []
            for s in cand_day_slots:
                st = s.get("slot_time", "")
                sh, sm = _parse_time(st)
                slot_dt = datetime(cand_date.year, cand_date.month, cand_date.day, sh, sm, tzinfo=tz)
                slot_utc = slot_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

                occupied = await execute(
                    """
                    SELECT 1 FROM tiktok_publications
                    WHERE destination_id = :did AND scheduled_publish_at = :utc
                    AND status IN ('queued', 'processing', 'scheduled', 'published')
                    LIMIT 1
                    """,
                    {"did": resolved_destination_id, "utc": slot_utc},
                )
                if not occupied.rows:
                    cand_open_slots.append((st, slot_utc, slot_dt))

            if cand_open_slots:
                target_date = cand_date
                target_slots = cand_open_slots[:cand_remaining]
                is_lookahead = True
                break

    if not target_slots:
        return {
            "ok": False,
            "reason": "NO_FUTURE_SLOTS",
            "message": "Không còn khung giờ phát hành trống nào trong hôm nay và các ngày kế tiếp đã đầy.",
            "daily_limit": max_daily,
        }

    # Query eligible unpublished videos from Inventory
    video_order = (schedule.get("video_order") or "newest").lower()
    order_clause = (
        "r.source_published_at DESC, r.discovered_at DESC, r.id DESC"
        if video_order == "newest"
        else "r.source_published_at ASC, r.discovered_at ASC, r.id ASC"
    )

    fetch_limit = len(target_slots) * 4
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

    upload_mode = pipeline.get("youtube_upload_mode") or "both"
    eligible_reels: list[dict[str, Any]] = []
    for r in candidate_reels:
        dur = r.get("duration")
        if upload_mode == "shorts" and dur and dur > 180:
            continue
        if upload_mode == "regular" and dur and dur <= 60:
            continue
        eligible_reels.append(r)
        if len(eligible_reels) >= len(target_slots):
            break

    if not eligible_reels:
        return {
            "ok": False,
            "reason": "NO_ELIGIBLE_INVENTORY",
            "message": f"Không có video phù hợp trong kho (cần định dạng '{upload_mode}').",
            "slots_available": len(target_slots),
            "target_date": target_date.isoformat() if target_date else None,
        }

    # Preview Mode (Dry Run)
    if dry_run:
        planned_items = []
        for i, reel_item in enumerate(eligible_reels[: len(target_slots)]):
            slot_label, slot_utc, slot_dt = target_slots[i]
            planned_items.append({
                "reel_id": reel_item.get("reel_id"),
                "caption": reel_item.get("caption") or "TikTok Video",
                "thumbnail_url": reel_item.get("thumbnail_url"),
                "duration": reel_item.get("duration"),
                "slot_time": slot_label,
                "scheduled_at": slot_utc,
                "scheduled_local": slot_dt.strftime("%Y-%m-%d %H:%M"),
            })

        day_label = "ngày mai" if is_lookahead else "hôm nay"
        target_str = target_date.strftime("%d/%m/%Y") if target_date else ""
        return {
            "ok": True,
            "dry_run": True,
            "target_date": target_date.isoformat() if target_date else "",
            "is_lookahead": is_lookahead,
            "planned_count": len(planned_items),
            "planned_slots": planned_items,
            "daily_limit": max_daily,
            "destination_name": dest.get("channel_name") or "YouTube",
            "message": f"Dự kiến lên lịch {len(planned_items)} video cho {day_label} ({target_str}).",
        }

    # Execution Mode: Enqueue jobs
    enqueued_jobs = []
    for i, reel_item in enumerate(eligible_reels[: len(target_slots)]):
        slot_label, slot_utc, slot_dt = target_slots[i]
        reel_db_id = reel_item["id"]

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

    target_date_str = target_date.isoformat() if target_date else today_date.isoformat()
    batch_id = f"batch_{secrets.token_hex(6)}"
    try:
        await schedules.create_batch(
            batch_id=batch_id,
            pipeline_id=pipeline_id,
            destination_id=resolved_destination_id,
            local_date=target_date_str,
            scheduled_batch_time=batch_time,
            planned_count=len(enqueued_jobs),
        )
    except Exception:
        pass

    result_data = {
        "ok": True,
        "videos_enqueued": len(enqueued_jobs),
        "slots": enqueued_jobs,
        "date": target_date_str,
        "is_lookahead": is_lookahead,
        "daily_limit": max_daily,
        "message": f"Đã lên lịch thành công {len(enqueued_jobs)} video cho ngày {target_date_str}.",
    }

    try:
        await system_state.set_json(
            f"scheduler:pipeline:{pipeline_id}:last_run",
            {
                "timestamp": _now_iso(),
                "ok": True,
                "reason": "SUCCESS",
                "message": result_data["message"],
                "videos_enqueued": len(enqueued_jobs),
                "target_date": target_date_str,
            },
        )
    except Exception:
        pass

    logger.info(
        "Scheduler enqueued %d video(s) for pipeline %s on %s (destination %s)",
        len(enqueued_jobs),
        pipeline_id,
        target_date_str,
        resolved_destination_id,
    )
    from .dashboard_cache import invalidate_pipeline
    invalidate_pipeline(pipeline_id)
    return result_data


async def execute_daily_batch(
    pipeline_id: str,
    destination_id: str | None = None,
    *,
    force_now: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Execute batch planning for pipeline."""
    return await calculate_schedule_plan(
        pipeline_id,
        destination_id=destination_id,
        force_now=force_now,
        now=now,
        dry_run=False,
    )


async def preview_daily_batch(
    pipeline_id: str,
    destination_id: str | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Dry-run preview of the next daily batch plan."""
    return await calculate_schedule_plan(
        pipeline_id,
        destination_id=destination_id,
        force_now=True,
        now=now,
        dry_run=True,
    )


async def get_scheduler_status(pipeline_id: str) -> dict[str, Any]:
    """Compile comprehensive scheduler and publisher runtime health and next-run metrics."""
    pipeline = await pipelines.get_pipeline(pipeline_id)
    if not pipeline:
        return {"ok": False, "reason": "PIPELINE_NOT_FOUND", "message": "Pipeline không tồn tại."}

    schedule = await schedules.get_by_pipeline(pipeline_id)
    if not schedule:
        schedule = await schedules.get_or_create_schedule(pipeline_id)

    dest = await destinations.get_default_destination(pipeline_id)
    if not dest:
        dest_list = await destinations.list_destinations(pipeline_id)
        connected = [d for d in dest_list if d.get("connected") and d.get("enabled")]
        if connected:
            dest = connected[0]

    tz_name = schedule.get("timezone") or _DEFAULT_TIMEZONE
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo(_DEFAULT_TIMEZONE)

    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(tz)
    batch_time = schedule.get("batch_time") or _DEFAULT_BATCH_TIME
    bh, bm = _parse_time(batch_time)
    today_batch = now_local.replace(hour=bh, minute=bm, second=0, microsecond=0)

    # Next scheduled run calculation
    if now_local < today_batch:
        next_run_dt = today_batch
    else:
        next_run_dt = today_batch + timedelta(days=1)
    next_scheduled_run = next_run_dt.isoformat()

    # Next publishing time from queue
    next_pub_res = await execute(
        """
        SELECT scheduled_at FROM tiktok_publish_queue
        WHERE pipeline_id = :pid AND status = 'queued' AND scheduled_at IS NOT NULL
        ORDER BY scheduled_at ASC LIMIT 1
        """,
        {"pid": pipeline_id},
    )
    next_publishing_time = next_pub_res.rows[0][0] if next_pub_res.rows else None

    # Scheduled jobs count
    q_res = await execute(
        "SELECT COUNT(*) FROM tiktok_publish_queue WHERE pipeline_id = :pid AND status = 'queued'",
        {"pid": pipeline_id},
    )
    scheduled_jobs_count = q_res.rows[0][0] if q_res.rows else 0

    # Eligible inventory count
    upload_mode = pipeline.get("youtube_upload_mode") or "both"
    inv_res = await execute(
        """
        SELECT r.duration FROM tiktok_reels r
        JOIN tiktok_sources s ON s.id = r.source_id
        WHERE s.pipeline_id = :pid AND s.enabled = 1 AND r.status IN ('new', 'active')
        """,
        {"pid": pipeline_id},
    )
    eligible_count = 0
    for r in inv_res.rows:
        dur = r[0]
        if upload_mode == "shorts" and dur and dur > 180:
            continue
        if upload_mode == "regular" and dur and dur <= 60:
            continue
        eligible_count += 1

    # Worker status
    sched_worker = await system_state.get_json("worker:scheduler", {})
    pub_worker = await system_state.get_json("worker:publisher", {})

    sched_online = False
    pub_online = False
    now_ts = time.time()
    if sched_worker and sched_worker.get("last_heartbeat"):
        try:
            hb_dt = datetime.fromisoformat(sched_worker["last_heartbeat"].replace("Z", "+00:00"))
            if abs(now_ts - hb_dt.timestamp()) < 120:
                sched_online = True
        except Exception:
            pass

    if pub_worker and pub_worker.get("last_heartbeat"):
        try:
            hb_dt = datetime.fromisoformat(pub_worker["last_heartbeat"].replace("Z", "+00:00"))
            if abs(now_ts - hb_dt.timestamp()) < 120:
                pub_online = True
        except Exception:
            pass

    # Last scheduler run
    last_run = await system_state.get_json(f"scheduler:pipeline:{pipeline_id}:last_run", None)

    # Determine reason summary
    if not sched_online:
        reason_code = "WORKER_OFFLINE"
        reason_message = "Scheduler worker chưa ghi nhận hoạt động."
    elif not schedule.get("enabled"):
        reason_code = "SCHEDULE_DISABLED"
        reason_message = "Lịch đăng tự động (Schedule) đang tắt."
    elif not pipeline.get("auto_publish"):
        reason_code = "AUTO_PUBLISH_DISABLED"
        reason_message = "Chế độ Auto Publish đang tắt."
    elif not dest:
        reason_code = "NO_DESTINATION"
        reason_message = "Chưa kết nối kênh YouTube đích."
    elif eligible_count == 0:
        reason_code = "NO_ELIGIBLE_INVENTORY"
        reason_message = f"Không có video đủ điều kiện trong kho (định dạng {upload_mode})."
    elif scheduled_jobs_count > 0:
        reason_code = "SCHEDULED"
        reason_message = f"Đang có {scheduled_jobs_count} video trong hàng đợi xuất bản."
    elif now_local < today_batch:
        diff_min = int((today_batch - now_local).total_seconds() // 60)
        h, m = divmod(diff_min, 60)
        reason_code = "WAITING_BATCH_TIME"
        reason_message = f"Chưa tới giờ chạy batch {batch_time} (còn {h}h {m}p)."
    else:
        reason_code = "READY"
        reason_message = "Hệ thống sẵn sàng lên lịch cho ngày tiếp theo."

    return {
        "ok": True,
        "pipeline_id": pipeline_id,
        "schedule_enabled": bool(schedule.get("enabled")),
        "auto_publish": bool(pipeline.get("auto_publish")),
        "timezone": tz_name,
        "batch_time": batch_time,
        "max_daily": int(schedule.get("max_daily_publish") or _DEFAULT_MAX_DAILY),
        "next_scheduled_run": next_scheduled_run,
        "last_scheduler_run": last_run.get("timestamp") if last_run else None,
        "last_scheduler_result": last_run,
        "next_publishing_time": next_publishing_time,
        "eligible_inventory": eligible_count,
        "scheduled_jobs": scheduled_jobs_count,
        "reason_code": reason_code,
        "reason_message": reason_message,
        "scheduler_worker_online": sched_online,
        "publisher_worker_online": pub_online,
        "publisher_status": "running" if (pub_worker.get("status") == "processing" and pub_online) else ("idle" if pub_online else "offline"),
    }
