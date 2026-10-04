"""Daily batch scheduler (Task 9). One batch per day per pipeline/destination.

Tick: enabled schedules -> local batch_time -> exactly-once daily batch ->
sequential publish up to max_daily_publish with YouTube publishAt slots.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from ..config import settings
from ..db.repositories import destinations, publications, reels, schedules
from .facebook_ai_metadata import MetadataError, ensure_ai_metadata
from .facebook_media import (
    TMP_ROOT,
    FacebookMediaError,
    FacebookMediaResolver,
    cleanup_job_dir,
    job_dir,
)
from .facebook_publish_worker import _PUBLISH_LOCK, run_publish_next
from .facebook_youtube_publisher import (
    YouTubePublisherError,
    finalize_description,
    load_destination_credentials_async,
    refresh_if_needed,
    upload_video,
    validate_publish_at,
    validate_visibility,
)

logger = logging.getLogger("backend-facebook.scheduler")

_DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"
_DEFAULT_BATCH_TIME = "06:00"
_DEFAULT_MAX_DAILY = 5

_SLOT_RE = schedules._SLOT_RE if hasattr(schedules, "_SLOT_RE") else None
if _SLOT_RE is None:
    import re as _re
    _SLOT_RE = _re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _now_utc(now=None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _parse_time(value: str) -> tuple[int, int]:
    if not _SLOT_RE.match(value.strip()):
        raise ValueError(f"Invalid time format: {value!r} (expected HH:MM).")
    hour, minute = value.split(":")
    return int(hour), int(minute)


def _slot_to_utc_rfc3339(date_iso: str, slot_time: str, tz_name: str) -> str:
    """Convert local HH:MM slot to UTC RFC3339 timestamp."""
    year, month, day = (int(p) for p in date_iso.split("-"))
    hour, minute = _parse_time(slot_time)
    tz = ZoneInfo(tz_name)
    local_dt = datetime(year, month, day, hour, minute, tzinfo=tz)
    utc_dt = local_dt.astimezone(timezone.utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _future_slots_for_today(schedule: dict, now_local: datetime) -> list[tuple[str, str]]:
    """Return (slot_time, utc_publish_at) for enabled future slots today."""
    tz_name = schedule.get("timezone") or _DEFAULT_TIMEZONE
    date_iso = now_local.date().isoformat()
    slots_by_day = schedule.get("slots", {})
    today_weekday = now_local.weekday()
    raw_slots = slots_by_day.get(today_weekday, [])
    if not raw_slots:
        return []

    future: list[tuple[str, str]] = []
    for slot in sorted(raw_slots):
        hour, minute = _parse_time(slot)
        slot_local = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if slot_local > now_local:
            utc_ts = _slot_to_utc_rfc3339(date_iso, slot, tz_name)
            future.append((slot, utc_ts))
    return future


async def _pick_destination(pipeline_id: str) -> tuple[dict | None, str | None]:
    """Single usable destination, else an error code. Never guesses."""
    usable = [
        d for d in await destinations.list_destinations(pipeline_id)
        if d.get("enabled", True) and d.get("connected") and d.get("channel_id")
    ]
    if not usable:
        return None, "NO_DESTINATION"
    if len(usable) > 1:
        return None, "AMBIGUOUS_DESTINATION"
    return usable[0], None


async def _ensure_batch(
    pipeline_id: str, destination_id: str, local_date: str, scheduled_batch_time: str
) -> tuple[str, bool]:
    """Claim exactly-once daily batch. Returns (batch_id, created)."""
    batch_id = f"batch_{uuid.uuid4().hex[:12]}"
    try:
        await schedules.create_batch(
            batch_id=batch_id,
            pipeline_id=pipeline_id,
            destination_id=destination_id,
            local_date=local_date,
            scheduled_batch_time=scheduled_batch_time,
        )
        return batch_id, True
    except Exception:
        return batch_id, False


async def run_scheduler_tick(
    now=None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    youtube_factory=None,
) -> dict[str, int]:
    """One lightweight tick. Only triggers daily batches whose time has passed."""
    utc_now = _now_utc(now)
    result = {"checked": 0, "batches_started": 0, "videos_scheduled": 0, "failed": 0}

    for schedule in await schedules.list_enabled_schedules():
        result["checked"] += 1
        pipeline_id = schedule["pipeline_id"]
        try:
            tz = ZoneInfo(schedule.get("timezone") or _DEFAULT_TIMEZONE)
        except Exception:
            logger.warning("invalid scheduler timezone for %s", pipeline_id)
            continue

        now_local = utc_now.astimezone(tz)
        date_iso = now_local.date().isoformat()
        batch_time = schedule.get("batch_time") or _DEFAULT_BATCH_TIME
        if not isinstance(batch_time, str) or ":" not in batch_time:
            logger.warning("unexpected batch_time for %s: %r", pipeline_id, batch_time)
            continue
        batch_hour, batch_minute = _parse_time(batch_time)
        batch_dt = now_local.replace(hour=batch_hour, minute=batch_minute, second=0, microsecond=0)

        if now_local < batch_dt:
            continue

        destination, dest_error = await _pick_destination(pipeline_id)
        if destination is None:
            logger.info("no destination for pipeline %s: %s", pipeline_id, dest_error)
            continue
        destination_id = destination["id"]

        existing = await schedules.get_batch(pipeline_id, destination_id, date_iso)
        if existing is not None:
            continue

        batch_id, claimed = await _ensure_batch(pipeline_id, destination_id, date_iso, batch_time)
        if not claimed:
            continue

        result["batches_started"] += 1
        try:
            scheduled = await _run_daily_batch(
                pipeline_id, destination_id, date_iso, batch_time, schedule,
                batch_id=batch_id, transport=transport, youtube_factory=youtube_factory,
            )
            result["videos_scheduled"] += scheduled
        except Exception as exc:
            logger.exception("daily batch failed for %s", pipeline_id)
            result["failed"] += 1
            try:
                await schedules.mark_batch_finished(batch_id, "failed", error=str(exc))
            except Exception:
                pass

    return result


async def _run_daily_batch(
    pipeline_id: str,
    destination_id: str,
    local_date: str,
    batch_time: str,
    schedule: dict,
    *,
    batch_id: str,
    transport: httpx.AsyncBaseTransport | None = None,
    youtube_factory=None,
) -> int:
    """Run one daily batch. Returns number of videos successfully scheduled."""
    await schedules.mark_batch_started(batch_id)
    max_daily = schedule.get("max_daily_publish") or _DEFAULT_MAX_DAILY
    slots = _future_slots_for_today(schedule, _now_utc().astimezone(ZoneInfo(schedule.get("timezone") or _DEFAULT_TIMEZONE)))
    if not slots:
        await schedules.mark_batch_finished(batch_id, "completed", planned_count=0, uploaded_count=0, failed_count=0)
        return 0

    quota = min(max_daily, len(slots))
    await schedules.update_batch_planned(batch_id, quota)

    scheduled_count = 0
    failed_count = 0
    for idx in range(quota):
        slot_time, utc_publish_at = slots[idx]
        try:
            ok = await _schedule_one_video(
                pipeline_id, destination_id, local_date, batch_time,
                slot_time, utc_publish_at, schedule,
                batch_id=batch_id, transport=transport, youtube_factory=youtube_factory,
            )
            if ok:
                scheduled_count += 1
            else:
                failed_count += 1
        except Exception as exc:
            logger.exception("video %d failed in batch %s", idx + 1, batch_id)
            failed_count += 1

    status = "completed" if scheduled_count > 0 else "no_work"
    await schedules.mark_batch_finished(
        batch_id, status, uploaded_count=scheduled_count, failed_count=failed_count,
    )
    return scheduled_count


async def _schedule_one_video(
    pipeline_id: str,
    destination_id: str,
    local_date: str,
    batch_time: str,
    slot_time: str,
    utc_publish_at: str,
    schedule: dict,
    *,
    batch_id: str,
    transport: httpx.AsyncBaseTransport | None = None,
    youtube_factory=None,
) -> bool:
    """Schedule exactly one video for one slot. Returns True on success."""
    if _PUBLISH_LOCK.locked():
        logger.warning("publish lock busy, skipping slot %s", slot_time)
        return False

    async with _PUBLISH_LOCK:
        return await _schedule_one_guarded(
            pipeline_id, destination_id, local_date, batch_time,
            slot_time, utc_publish_at, schedule,
            batch_id=batch_id, transport=transport, youtube_factory=youtube_factory,
        )


async def _schedule_one_guarded(
    pipeline_id: str,
    destination_id: str,
    local_date: str,
    batch_time: str,
    slot_time: str,
    utc_publish_at: str,
    schedule: dict,
    *,
    batch_id: str,
    transport: httpx.AsyncBaseTransport | None = None,
    youtube_factory=None,
) -> bool:
    """Guarded single-video schedule. No lock held across await."""
    destination = await destinations.get_destination(destination_id)
    if destination is None:
        logger.error("destination missing for pipeline %s", pipeline_id)
        return False

    if not await schedules.has_new_inventory(pipeline_id):
        logger.info("no new inventory for pipeline %s", pipeline_id)
        return False

    reel, claimed = await reels.claim_next_reel(pipeline_id)
    if not claimed or reel is None:
        logger.info("no claimable reel for pipeline %s", pipeline_id)
        return False

    reel_db_id = reel["id"]
    reel_id = reel["reel_id"]
    job_id = f"sch_{uuid.uuid4().hex[:12]}"
    target_dir = job_dir(job_id, TMP_ROOT)
    publication_id = f"pub_{uuid.uuid4().hex[:12]}"

    try:
        publication, _ = await publications.get_or_create(
            publication_id=publication_id, reel_db_id=reel_db_id, destination_id=destination_id
        )
        if publication["status"] == "published":
            await reels.release_claim(reel_db_id)
            cleanup_job_dir(target_dir)
            return True

        await publications.mark_processing(publication["id"])
        if not await reels.advance_status(reel_db_id, "queued", "processing"):
            await publications.mark_failed(publication["id"], "CLAIM_LOST")
            cleanup_job_dir(target_dir)
            return False

        try:
            ensured = await ensure_ai_metadata(reel, transport=transport)
        except MetadataError as exc:
            await publications.mark_failed(publication["id"], f"AI_FAILED: {exc.code}")
            await reels.record_reel_error(reel_db_id, f"AI_FAILED: {exc.code}")
            await reels.release_claim(reel_db_id)
            cleanup_job_dir(target_dir)
            return False

        ai_title = (ensured.metadata.title or "").strip()
        if not ai_title or len(ai_title) > 100:
            await publications.mark_failed(publication["id"], "AI_METADATA_INVALID")
            await reels.record_reel_error(reel_db_id, "AI_METADATA_INVALID")
            await reels.release_claim(reel_db_id)
            cleanup_job_dir(target_dir)
            return False

        ai_description = finalize_description(ensured.metadata.description, ensured.metadata.hashtags)

        try:
            resolver = FacebookMediaResolver.from_settings(transport=transport)
        except FacebookMediaError as exc:
            await publications.mark_failed(publication["id"], f"MEDIA_SETUP_FAILED: {exc.code}")
            await reels.record_reel_error(reel_db_id, f"MEDIA_SETUP_FAILED: {exc.code}")
            await reels.release_claim(reel_db_id)
            cleanup_job_dir(target_dir)
            return False

        try:
            media = await resolver.resolve(reel.get("reel_url") or "")
            output = await resolver.download_media(media, job_id, tmp_root=TMP_ROOT)
            file_bytes = output.stat().st_size
            if file_bytes <= 0:
                raise FacebookMediaError("MEDIA_DOWNLOAD_FAILED", "Downloaded file is empty.")
        except Exception as exc:
            code = exc.code if isinstance(exc, FacebookMediaError) else "DOWNLOAD_FAILED"
            msg = str(exc)
            await publications.mark_failed(publication["id"], f"DOWNLOAD_FAILED: {code}")
            await reels.record_reel_error(reel_db_id, f"DOWNLOAD_FAILED: {code}")
            await reels.release_claim(reel_db_id)
            cleanup_job_dir(target_dir)
            return False

        try:
            credentials = await load_destination_credentials_async(destination_id)
            credentials = await refresh_if_needed(destination_id, credentials)
            validated_publish_at = validate_publish_at(utc_publish_at)
            youtube_video_id = await __import__('asyncio').to_thread(
                upload_video, credentials, output, ai_title, ai_description,
                "private", publish_at=validated_publish_at,
                youtube_factory=youtube_factory,
            )
        except YouTubePublisherError as exc:
            await publications.mark_failed(publication["id"], f"YT_UPLOAD_FAILED: {exc.code}")
            await reels.record_reel_error(reel_db_id, f"YT_UPLOAD_FAILED: {exc.code}")
            await reels.release_claim(reel_db_id)
            cleanup_job_dir(target_dir)
            return False
        except Exception as exc:
            await publications.mark_failed(publication["id"], f"YT_UPLOAD_UNEXPECTED: {type(exc).__name__}")
            await reels.record_reel_error(reel_db_id, f"YT_UPLOAD_UNEXPECTED: {type(exc).__name__}")
            await reels.release_claim(reel_db_id)
            cleanup_job_dir(target_dir)
            return False

        try:
            await publications.mark_scheduled(
                publication["id"], youtube_video_id,
                scheduled_publish_at=utc_publish_at,
                title=ai_title, description=ai_description,
                hashtags=ensured.metadata.hashtags, ai_model=ensured.model,
            )
            await reels.mark_reel_scheduled(reel_db_id, youtube_video_id)
        except Exception as exc:
            cleanup_job_dir(target_dir)
            await reels.release_claim(reel_db_id)
            logger.exception("DB persist failed after upload vid=%s", youtube_video_id)
            return False

        cleanup_job_dir(target_dir)
        logger.info(
            "scheduled reel %s video %s slot %s publishAt %s",
            reel_id, youtube_video_id, slot_time, utc_publish_at,
        )
        return True

    except Exception as exc:
        logger.exception("unexpected error scheduling video in batch %s", batch_id)
        try:
            await publications.mark_failed(publication_id, f"BATCH_ERROR: {type(exc).__name__}")
        except Exception:
            pass
        try:
            await reels.release_claim(reel_db_id)
        except Exception:
            pass
        cleanup_job_dir(target_dir)
        return False


async def describe_schedule_status(pipeline_id: str, now=None) -> dict | None:
    """Data for GET schedule/status. None when no schedule row exists."""
    from ..db.repositories import pipelines

    pipeline = await pipelines.get_pipeline(pipeline_id)
    if pipeline is None:
        return None
    schedule = await schedules.get_schedule(pipeline_id)
    utc_now = _now_utc(now)
    if schedule is None:
        return {
            "date": utc_now.date().isoformat(),
            "timezone": _DEFAULT_TIMEZONE,
            "batch_time": _DEFAULT_BATCH_TIME,
            "batch_status": "idle",
            "scheduled_today": 0,
            "daily_limit": _DEFAULT_MAX_DAILY,
            "slots": [],
            "scheduler_enabled": False,
        }
    now_local = utc_now.astimezone(ZoneInfo(schedule.get("timezone") or _DEFAULT_TIMEZONE))
    date_iso = now_local.date().isoformat()
    batch = await schedules.get_batch_for_pipeline_date(pipeline_id, date_iso)
    batch_status = "idle"
    if batch:
        if batch["status"] in ("queued", "running"):
            batch_status = "running"
        elif batch["status"] == "completed":
            batch_status = "completed"
        elif batch["status"] == "failed":
            batch_status = "failed"
        elif batch["status"] == "no_work":
            batch_status = "no_work"

    slots = []
    for day in range(7):
        day_slots = schedule.get("slots", {}).get(day, [])
        for slot in sorted(day_slots):
            slots.append({
                "weekday": day,
                "time": slot,
                "enabled": True,
            })

    utc_today = utc_now.date().isoformat()
    next_batch_dt = None
    if schedule.get("enabled"):
        batch_time = schedule.get("batch_time") or _DEFAULT_BATCH_TIME
        batch_hour, batch_minute = _parse_time(batch_time)
        tz = ZoneInfo(schedule.get("timezone") or _DEFAULT_TIMEZONE)
        local_now = utc_now.astimezone(tz)
        candidate = local_now.replace(hour=batch_hour, minute=batch_minute, second=0, microsecond=0)
        if candidate <= local_now:
            candidate = candidate + timedelta(days=1)
        next_batch_dt = candidate.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "date": date_iso,
        "weekday": now_local.weekday(),
        "timezone": schedule.get("timezone") or _DEFAULT_TIMEZONE,
        "batch_time": schedule.get("batch_time") or _DEFAULT_BATCH_TIME,
        "batch_status": batch_status,
        "scheduled_today": batch["uploaded_count"] if batch else 0,
        "daily_limit": schedule.get("max_daily_publish") or _DEFAULT_MAX_DAILY,
        "next_batch_at": next_batch_dt,
        "slots": slots,
        "scheduler_enabled": bool(schedule.get("enabled")),
    }
