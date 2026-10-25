"""Daily batch scheduler (Task 9). One batch per day per pipeline/destination.

Tick: enabled schedules -> local batch_time -> exactly-once daily batch ->
sequential enqueue up to max_daily_publish with YouTube publishAt slots.

Global publisher worker handles the actual processing.

Both the automatic tick and the manual "run batch now" button funnel through
`execute_daily_batch`. Only the batch_time gate differs (`force_now`).
Publish-slot selection, the daily limit, AI-ready selection and durable
enqueue are shared, so the two paths cannot drift apart.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from ..config import settings
from ..db.repositories import destinations, publications, reels, schedules, publish_queue
from ..db.repositories import ai_settings as ai_settings_repo
from ..db.repositories import quota as quota_repo

logger = logging.getLogger("backend-facebook.scheduler")

_DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"
_DEFAULT_BATCH_TIME = "06:00"
_DEFAULT_MAX_DAILY = 5

_SLOT_RE = schedules._SLOT_RE if hasattr(schedules, "_SLOT_RE") else None
if _SLOT_RE is None:
    import re as _re
    _SLOT_RE = _re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


# Reasons returned when nothing (or nothing new) was enqueued. Surfaced to the UI.
REASON_MESSAGES: dict[str, str] = {
    "NO_DESTINATION": "Chưa có kênh YouTube đã kết nối cho pipeline này.",
    "NO_FUTURE_SLOTS": "Hôm nay không còn khung giờ phát hành nào ở tương lai.",
    "NO_AI_READY_INVENTORY": "Chưa có video nào sẵn sàng (cần AI metadata khớp cấu hình).",
    "DAILY_LIMIT_REACHED": "Đã đạt giới hạn phát hành trong ngày.",
    "BATCH_ALREADY_COMPLETED": "Batch hôm nay đã chạy xong.",
    "BATCH_IN_PROGRESS": "Batch hôm nay đang chạy.",
    "NOT_BEFORE_BATCH_TIME": "Chưa tới giờ chạy batch tự động.",
    "SCHEDULE_NOT_FOUND": "Chưa cấu hình lịch cho pipeline này.",
    "ENQUEUE_ERROR": "Lỗi khi đưa video vào hàng đợi.",
    "QUOTA_PAUSED": "YouTube đang tạm dừng do quota/rate limit. Scheduler sẽ tự thử lại.",
    "AUTO_PUBLISH_DISABLED": "Auto Publish đang tắt cho pipeline này. Bật AUTO ON để tiếp tục lịch đăng.",
}


def reason_message(code: str | None) -> str | None:
    if not code:
        return None
    return REASON_MESSAGES.get(code, code)


def _batch_result(
    *,
    batch_id: str | None = None,
    batch_status: str | None = None,
    videos_enqueued: int = 0,
    slots: list[dict[str, str]] | None = None,
    reason: str | None = None,
    date: str | None = None,
    daily_limit: int | None = None,
    slot_capacity: int | None = None,
    capacity_limited: bool = False,
    warning: str | None = None,
) -> dict:
    return {
        "ok": videos_enqueued > 0,
        "batch_id": batch_id,
        "batch_status": batch_status,
        "videos_enqueued": videos_enqueued,
        "slots": slots or [],
        "reason": reason,
        "message": reason_message(reason) if videos_enqueued == 0 else warning,
        "warning": warning,
        "date": date,
        "daily_limit": daily_limit,
        "slot_capacity": slot_capacity,
        "capacity_limited": capacity_limited,
    }


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


def _local_day_bounds_utc(day, tz: ZoneInfo) -> tuple[str, str]:
    """UTC [start, end) bounds for a local calendar day."""
    start_local = datetime(day.year, day.month, day.day, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        end_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def _capacity_warning(daily_limit: int, feasible: int) -> str | None:
    if feasible >= daily_limit:
        return None
    return (
        f"Max videos/day = {daily_limit} nhưng hôm nay chỉ có {feasible} lượt khả thi "
        f"(không đủ khung giờ còn lại). Thêm slot trong Lịch tuần để đăng đủ."
    )


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


async def _resolve_destination(pipeline_id: str, destination_id: str) -> tuple[dict | None, str | None]:
    """Validate the destination belongs to the pipeline and is usable."""
    dest = await destinations.get_destination(destination_id)
    if dest is None or dest.get("pipeline_id") != pipeline_id:
        return None, "NO_DESTINATION"
    if not dest.get("enabled", True):
        return None, "NO_DESTINATION"
    if not dest.get("connected") or not dest.get("channel_id"):
        return None, "NO_DESTINATION"
    return dest, None


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


async def execute_daily_batch(
    pipeline_id: str,
    destination_id: str,
    *,
    force_now: bool = False,
    now=None,
    transport: httpx.AsyncBaseTransport | None = None,
    youtube_factory=None,
) -> dict:
    """Plan and durably enqueue today's daily batch. Does no heavy work.

    `force_now=True` (manual "run batch now") bypasses ONLY the batch_time gate.
    It never bypasses:
      - publish slot selection (always future-only, never backfilled)
      - max_daily_publish
      - the AI-ready requirement
      - destination readiness
      - publish queue concurrency (enforced by the global publisher worker)

    Additionally, a manual run on top of an already-completed batch tops up
    free future slots (never taken twice, never over the daily limit) instead
    of reporting BATCH_ALREADY_COMPLETED. The automatic tick never tops up.

    `force_now=False` (automatic tick) additionally waits for batch_time.
    """
    utc_now = _now_utc(now)
    schedule = await schedules.get_schedule(pipeline_id)
    if schedule is None:
        return _batch_result(reason="SCHEDULE_NOT_FOUND")

    # Auto Publish gate: the automatic tick must never enqueue/upload when
    # the pipeline opted out. Manual "run batch now" (force_now=True) is an
    # explicit user action and still runs. Checked BEFORE any batch row is
    # inserted so the daily UNIQUE row is not burned.
    if not force_now:
        from ..db.repositories import pipelines as pipelines_repo

        pipeline = await pipelines_repo.get_pipeline(pipeline_id)
        if pipeline is not None and not pipeline.get("auto_publish", True):
            logger.info("auto publish disabled for pipeline %s, skipping automatic batch", pipeline_id)
            return _batch_result(reason="AUTO_PUBLISH_DISABLED")

    try:
        tz = ZoneInfo(schedule.get("timezone") or _DEFAULT_TIMEZONE)
    except Exception:
        logger.warning("invalid scheduler timezone for %s", pipeline_id)
        return _batch_result(reason="SCHEDULE_NOT_FOUND")

    now_local = utc_now.astimezone(tz)
    date_iso = now_local.date().isoformat()
    batch_time = schedule.get("batch_time") or _DEFAULT_BATCH_TIME

    quota_pause = await quota_repo.get_active_pause(pipeline_id, now=utc_now)
    if quota_pause is not None:
        return _batch_result(
            reason="QUOTA_PAUSED",
            date=date_iso,
            daily_limit=int(schedule.get("max_daily_publish") or _DEFAULT_MAX_DAILY),
        )

    destination, dest_error = await _resolve_destination(pipeline_id, destination_id)
    if destination is None:
        return _batch_result(reason=dest_error or "NO_DESTINATION", date=date_iso)

    # Automatic gate, evaluated BEFORE any batch row is inserted so the daily
    # UNIQUE(pipeline_id, destination_id, local_date) row is not burned early.
    if not force_now:
        batch_hour, batch_minute = _parse_time(batch_time)
        batch_dt = now_local.replace(hour=batch_hour, minute=batch_minute, second=0, microsecond=0)
        if now_local < batch_dt:
            return _batch_result(reason="NOT_BEFORE_BATCH_TIME", date=date_iso)

    # Slots are future-only for BOTH paths: force_now must not backfill.
    slots = _future_slots_for_today(schedule, now_local)

    max_daily = max(1, int(schedule.get("max_daily_publish") or _DEFAULT_MAX_DAILY))
    slot_capacity = len(slots)
    feasible = min(max_daily, slot_capacity)
    capacity_limited = max_daily > slot_capacity
    capacity_warning = _capacity_warning(max_daily, feasible) if capacity_limited else None
    result_ctx = {
        "daily_limit": max_daily,
        "slot_capacity": slot_capacity,
        "capacity_limited": capacity_limited,
        "warning": capacity_warning,
    }

    existing = await schedules.get_batch(pipeline_id, destination_id, date_iso)
    topping_up = bool(
        force_now and existing is not None and existing["status"] == "completed"
    )
    if existing is not None:
        batch_status = existing["status"]
        if batch_status == "running":
            return _batch_result(
                batch_id=existing["id"],
                batch_status=batch_status,
                videos_enqueued=0,
                reason="BATCH_IN_PROGRESS",
                date=date_iso,
                **result_ctx,
            )
        # Completed + automatic tick: never re-run the same day twice.
        # Completed + manual run: allow topping up free future slots below.
        if batch_status == "completed" and not topping_up:
            return _batch_result(
                batch_id=existing["id"],
                batch_status=batch_status,
                videos_enqueued=existing["uploaded_count"] or 0,
                reason="BATCH_ALREADY_COMPLETED",
                date=date_iso,
                **result_ctx,
            )
        # 'no_work' / 'failed' stay re-runnable: inventory or AI metadata may have
        # changed since. Already-enqueued reels left status 'new' -> 'queued' and
        # publications.get_or_create dedups on (reel, destination), so a re-run
        # cannot create a duplicate.
        batch_id = existing["id"]
        already_enqueued = existing["uploaded_count"] or 0
        planned_before = existing["planned_count"] or 0
        failed_before = existing["failed_count"] or 0
    else:
        batch_id, claimed = await _ensure_batch(pipeline_id, destination_id, date_iso, batch_time)
        if not claimed:
            return _batch_result(reason="BATCH_ALREADY_COMPLETED", date=date_iso)
        already_enqueued = 0
        planned_before = 0
        failed_before = 0

    if not slots:
        if topping_up:
            return _batch_result(
                batch_id=batch_id,
                batch_status="completed",
                videos_enqueued=already_enqueued,
                reason="BATCH_ALREADY_COMPLETED",
                date=date_iso,
                **result_ctx,
            )
        return _batch_result(reason="NO_FUTURE_SLOTS", date=date_iso, **result_ctx)

    if topping_up:
        # Manual top-up of a completed batch: only slots nobody took yet,
        # capped by the remaining daily quota. Dedup (claim + get_or_create)
        # makes double-booking impossible.
        from ..db.repositories import publications as publications_repo

        used_times = set(
            await publications_repo.used_slot_times_for_date(
                pipeline_id, date_iso, schedule.get("timezone") or _DEFAULT_TIMEZONE
            )
        )
        plan_slots = [s for s in slots if s[0] not in used_times]
        remaining = min(max_daily - already_enqueued, len(plan_slots))
        if remaining <= 0:
            return _batch_result(
                batch_id=batch_id,
                batch_status="completed",
                videos_enqueued=already_enqueued,
                reason="BATCH_ALREADY_COMPLETED",
                date=date_iso,
                **result_ctx,
            )
        # Only top up when new AI-ready work actually exists; otherwise a
        # plain double-click would flip a friendly BATCH_ALREADY_COMPLETED
        # into NO_AI_READY noise.
        _, top_up_hash = await ai_settings_repo.current_config_hash(pipeline_id)
        if not await reels.list_ai_ready_reels(pipeline_id, top_up_hash):
            return _batch_result(
                batch_id=batch_id,
                batch_status="completed",
                videos_enqueued=already_enqueued,
                reason="BATCH_ALREADY_COMPLETED",
                date=date_iso,
                **result_ctx,
            )
    else:
        quota = min(max_daily, len(slots))
        remaining = quota - already_enqueued
        if remaining <= 0:
            return _batch_result(
                batch_id=batch_id,
                batch_status=(existing or {}).get("status", "planned"),
                reason="DAILY_LIMIT_REACHED",
                date=date_iso,
                **result_ctx,
            )
        plan_slots = slots

    await schedules.mark_batch_started(batch_id)
    await schedules.update_batch_planned(batch_id, max(planned_before, already_enqueued + remaining))

    enqueued = 0
    failed = 0
    used_slots: list[dict[str, str]] = []
    failure_reasons: list[str] = []

    for offset in range(remaining):
        slot_index = already_enqueued + offset
        slot_time, utc_publish_at = plan_slots[offset]
        try:
            ok, failure = await _enqueue_one_video(
                pipeline_id, destination_id, date_iso, batch_time,
                slot_time, utc_publish_at, schedule,
                batch_id=batch_id, transport=transport, youtube_factory=youtube_factory,
                slot_index=slot_index,
            )
        except Exception:
            logger.exception("slot %s failed in batch %s", slot_time, batch_id)
            ok, failure = False, "ENQUEUE_ERROR"
        if ok:
            enqueued += 1
            used_slots.append({"slot": slot_time, "publish_at": utc_publish_at})
        else:
            failed += 1
            if failure:
                failure_reasons.append(failure)

    # A top-up that added nothing keeps the previous completed state instead
    # of downgrading to no_work.
    if enqueued > 0 or already_enqueued > 0:
        final_status = "completed"
    else:
        final_status = "no_work"
    await schedules.mark_batch_finished(
        batch_id, final_status,
        uploaded_count=already_enqueued + enqueued,
        failed_count=failed_before + failed,
    )

    if enqueued == 0:
        reason = failure_reasons[0] if failure_reasons else "NO_AI_READY_INVENTORY"
        logger.info("batch %s enqueued nothing (reason=%s)", batch_id, reason)
        return _batch_result(
            batch_id=batch_id,
            batch_status=final_status,
            reason=reason,
            date=date_iso,
            **result_ctx,
        )

    logger.info(
        "batch %s enqueued %d video(s) into publish queue: %s",
        batch_id, enqueued, [s["slot"] for s in used_slots],
    )
    return _batch_result(
        batch_id=batch_id,
        batch_status=final_status,
        videos_enqueued=enqueued,
        slots=used_slots,
        date=date_iso,
        **result_ctx,
    )


async def run_scheduler_tick(
    now=None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    youtube_factory=None,
) -> dict[str, int]:
    """One lightweight automatic tick. Still respects batch_time."""
    utc_now = _now_utc(now)
    result = {"checked": 0, "batches_started": 0, "videos_enqueued": 0, "failed": 0}

    for schedule in await schedules.list_enabled_schedules():
        result["checked"] += 1
        pipeline_id = schedule["pipeline_id"]
        try:
            ZoneInfo(schedule.get("timezone") or _DEFAULT_TIMEZONE)
        except Exception:
            logger.warning("invalid scheduler timezone for %s", pipeline_id)
            continue

        destination, dest_error = await _pick_destination(pipeline_id)
        if destination is None:
            continue

        try:
            outcome = await execute_daily_batch(
                pipeline_id, destination["id"],
                force_now=False, now=utc_now,
                transport=transport, youtube_factory=youtube_factory,
            )
        except Exception:
            logger.exception("daily batch failed for %s", pipeline_id)
            result["failed"] += 1
            continue

        if outcome["videos_enqueued"]:
            result["batches_started"] += 1
            result["videos_enqueued"] += outcome["videos_enqueued"]

    return result


async def _enqueue_one_video(
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
    slot_index: int = 0,
) -> tuple[bool, str | None]:
    """Enqueue exactly one video for one slot. Returns (ok, failure_reason)."""
    from ..db.repositories import reels as reels_repo

    destination = await destinations.get_destination(destination_id)
    if destination is None:
        logger.error("destination missing for pipeline %s", pipeline_id)
        return False, "NO_DESTINATION"

    pipe_ai_settings, config_hash = await ai_settings_repo.current_config_hash(pipeline_id)
    ai_enabled = pipe_ai_settings.get("enabled", True)

    if not ai_enabled:
        # AI disabled: scheduling requires AI, so nothing is picked.
        logger.info("AI disabled for pipeline %s, skipping scheduling", pipeline_id)
        return False, "NO_AI_READY_INVENTORY"

    # AI-first: only pick reels with generated AI metadata matching current config.
    reels_with_ai = await reels_repo.list_ai_ready_reels(pipeline_id, config_hash)
    if not reels_with_ai:
        logger.info("no AI-ready reels for pipeline %s", pipeline_id)
        return False, "NO_AI_READY_INVENTORY"

    reel = None
    for candidate in reels_with_ai:
        if await reels_repo.advance_status(candidate["id"], "new", "queued"):
            reel = candidate
            break

    if reel is None:
        logger.info("no claimable AI-ready reel for pipeline %s", pipeline_id)
        return False, "NO_AI_READY_INVENTORY"

    reel_db_id = reel["id"]
    reel_id = reel["reel_id"]
    publication_id = f"pub_{uuid.uuid4().hex[:12]}"

    try:
        publication, _ = await publications.get_or_create(
            publication_id=publication_id, reel_db_id=reel_db_id, destination_id=destination_id
        )
        if publication["status"] == "published":
            await reels_repo.release_claim(reel_db_id)
            return True, None

        # Persist scheduled_publish_at (utc_publish_at) on the publication.
        await publications.set_scheduled_publish_at(publication["id"], utc_publish_at)

        # Snapshot the requested upload mode at enqueue time: later settings
        # changes must not rewrite history for already-queued jobs.
        try:
            from ..db.repositories import pipelines as pipelines_repo

            pipe = await pipelines_repo.get_pipeline(pipeline_id)
            await publications.set_upload_snapshot(
                publication["id"], (pipe or {}).get("youtube_upload_mode") or "video"
            )
        except Exception:
            logger.exception("failed to snapshot upload mode for publication %s", publication["id"])

        # Publication stays 'queued'; the global publisher marks it 'processing'.
        # Earlier slots get higher queue priority.
        priority = 1000 - slot_index
        await publish_queue.enqueue_publish_job(
            pipeline_id=pipeline_id,
            destination_id=destination_id,
            reel_db_id=reel_db_id,
            publication_id=publication["id"],
            priority=priority,
        )

        logger.info(
            "enqueued reel %s for slot %s publishAt %s queue_priority=%d",
            reel_id, slot_time, utc_publish_at, priority,
        )
        return True, None

    except Exception as exc:
        logger.exception("unexpected error enqueueing video in batch %s", batch_id)
        try:
            await publications.mark_failed(publication_id, f"ENQUEUE_ERROR: {type(exc).__name__}")
        except Exception:
            pass
        try:
            await reels_repo.release_claim(reel_db_id)
        except Exception:
            pass
        return False, "ENQUEUE_ERROR"


async def refill_slot_after_failure(
    *,
    pipeline_id: str,
    destination_id: str,
    scheduled_publish_at: str | None,
    failed_reel_db_id: str,
    now=None,
) -> dict:
    """Replace a video-specific failure with the next AI-ready reel.

    The failed publication no longer counts as committed, so the replacement
    keeps the same YouTube publishAt without exceeding the daily limit. The
    failed reel must already be skipped/terminal so it cannot be selected
    again. Returns a small result dict; never raises for ordinary no-op cases.
    """
    if not scheduled_publish_at:
        return {"refilled": False, "reason": "NO_SLOT"}

    try:
        publish_dt = datetime.fromisoformat(str(scheduled_publish_at).replace("Z", "+00:00"))
        if publish_dt.tzinfo is None:
            return {"refilled": False, "reason": "INVALID_SLOT"}
        publish_dt = publish_dt.astimezone(timezone.utc)
    except Exception:
        return {"refilled": False, "reason": "INVALID_SLOT"}

    utc_now = _now_utc(now)
    if publish_dt <= utc_now + timedelta(seconds=60):
        return {"refilled": False, "reason": "SLOT_TOO_CLOSE"}

    schedule = await schedules.get_schedule(pipeline_id)
    if schedule is None:
        return {"refilled": False, "reason": "SCHEDULE_NOT_FOUND"}

    # A failure finishing after Auto was turned off must not enqueue a
    # replacement video. The failed slot simply stays empty until Auto is on.
    from ..db.repositories import pipelines as pipelines_repo

    pipeline = await pipelines_repo.get_pipeline(pipeline_id)
    if pipeline is not None and not pipeline.get("auto_publish", True):
        return {"refilled": False, "reason": "AUTO_PUBLISH_DISABLED"}

    if await quota_repo.get_active_pause(pipeline_id, now=utc_now) is not None:
        return {"refilled": False, "reason": "QUOTA_PAUSED"}

    tz = ZoneInfo(schedule.get("timezone") or _DEFAULT_TIMEZONE)
    local_dt = publish_dt.astimezone(tz)
    local_date = local_dt.date().isoformat()
    start_utc, end_utc = _local_day_bounds_utc(local_dt.date(), tz)
    stats = await publications.scheduler_day_stats(
        pipeline_id,
        start_utc_iso=start_utc,
        end_utc_iso=end_utc,
        now_utc_iso=utc_now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    daily_limit = max(1, int(schedule.get("max_daily_publish") or _DEFAULT_MAX_DAILY))
    if int(stats.get("committed_today") or 0) >= daily_limit:
        return {"refilled": False, "reason": "DAILY_LIMIT_REACHED"}

    batch = await schedules.get_batch_for_pipeline_date(pipeline_id, local_date)
    batch_id = batch["id"] if batch else f"refill_{uuid.uuid4().hex[:12]}"
    slot_time = local_dt.strftime("%H:%M")
    normalized_publish_at = publish_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    ok, failure = await _enqueue_one_video(
        pipeline_id,
        destination_id,
        local_date,
        (schedule.get("batch_time") or _DEFAULT_BATCH_TIME),
        slot_time,
        normalized_publish_at,
        schedule,
        batch_id=batch_id,
        slot_index=0,
    )
    if ok:
        logger.info(
            "refilled slot %s (%s) for pipeline %s after reel %s failed",
            slot_time,
            normalized_publish_at,
            pipeline_id,
            failed_reel_db_id,
        )
    return {
        "refilled": ok,
        "reason": failure,
        "slot": slot_time,
        "scheduled_publish_at": normalized_publish_at,
    }


async def describe_schedule_status(pipeline_id: str, now=None) -> dict | None:
    """Data for GET schedule/status. None when the pipeline does not exist."""
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
            "published_today": 0,
            "committed_today": 0,
            "remaining_today": _DEFAULT_MAX_DAILY,
            "feasible_today": 0,
            "future_slots_today": 0,
            "slots_today": 0,
            "next_publish_at": None,
            "scheduler_state": "waiting",
            "quota_paused_until": None,
            "quota_pause_reason": None,
            "capacity_warning": None,
            "daily_limit": _DEFAULT_MAX_DAILY,
            "slots": [],
            "scheduler_enabled": False,
        }

    tz = ZoneInfo(schedule.get("timezone") or _DEFAULT_TIMEZONE)
    now_local = utc_now.astimezone(tz)
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

    daily_limit = max(1, int(schedule.get("max_daily_publish") or _DEFAULT_MAX_DAILY))
    day_start, day_end = _local_day_bounds_utc(now_local.date(), tz)
    day_stats = await publications.scheduler_day_stats(
        pipeline_id,
        start_utc_iso=day_start,
        end_utc_iso=day_end,
        now_utc_iso=utc_now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    committed_today = int(day_stats.get("committed_today") or 0)
    published_today = int(day_stats.get("published_today") or 0)

    used_times = set(
        await publications.used_slot_times_for_date(
            pipeline_id, date_iso, schedule.get("timezone") or _DEFAULT_TIMEZONE
        )
    )
    future_slots = [
        slot for slot in _future_slots_for_today(schedule, now_local)
        if slot[0] not in used_times
    ]
    future_slots_today = len(future_slots)
    slots_today = len(schedule.get("slots", {}).get(now_local.weekday(), []))
    feasible_today = min(daily_limit, committed_today + future_slots_today)
    remaining_today = max(0, daily_limit - committed_today)
    capacity_warning = _capacity_warning(daily_limit, feasible_today)

    quota_pause = await quota_repo.get_active_pause(pipeline_id, now=utc_now)
    counts = await _ai_readiness_counts(pipeline_id, batch)
    if quota_pause is not None:
        scheduler_state = "quota_paused"
    elif batch_status == "running" or (counts.get("queue_processing") or 0) > 0:
        scheduler_state = "running"
    elif committed_today >= daily_limit:
        scheduler_state = "daily_limit_reached"
    elif (counts.get("inventory_total") or 0) == 0:
        scheduler_state = "no_inventory"
    else:
        scheduler_state = "waiting"

    next_batch_dt = None
    if schedule.get("enabled"):
        batch_time = schedule.get("batch_time") or _DEFAULT_BATCH_TIME
        batch_hour, batch_minute = _parse_time(batch_time)
        candidate = now_local.replace(hour=batch_hour, minute=batch_minute, second=0, microsecond=0)
        if candidate <= now_local:
            candidate = candidate + timedelta(days=1)
        next_batch_dt = candidate.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "date": date_iso,
        "weekday": now_local.weekday(),
        "timezone": schedule.get("timezone") or _DEFAULT_TIMEZONE,
        "batch_time": schedule.get("batch_time") or _DEFAULT_BATCH_TIME,
        "batch_status": batch_status,
        "scheduled_today": batch["uploaded_count"] if batch else 0,
        "published_today": published_today,
        "committed_today": committed_today,
        "remaining_today": remaining_today,
        "feasible_today": feasible_today,
        "future_slots_today": future_slots_today,
        "slots_today": slots_today,
        "next_publish_at": day_stats.get("next_publish_at"),
        "scheduler_state": scheduler_state,
        "quota_paused_until": (quota_pause or {}).get("paused_until"),
        "quota_pause_reason": (quota_pause or {}).get("reason"),
        "capacity_warning": capacity_warning,
        "daily_limit": daily_limit,
        "next_batch_at": next_batch_dt,
        "slots": slots,
        "scheduler_enabled": bool(schedule.get("enabled")),
        **counts,
    }


async def _ai_readiness_counts(
    pipeline_id: str, batch: dict | None = None
) -> dict:
    """Additive counters so the UI can tell Inventory apart from AI-ready,
    plus today's batch detail and per-pipeline queue depth.

    Never raises: on any error returns zeros rather than breaking status.
    """
    fallback = {
        "inventory_total": 0,
        "ai_generated": 0,
        "ai_pending": 0,
        "ai_failed": 0,
        "ai_ready": 0,
        "queue_queued": 0,
        "queue_processing": 0,
        "queue_scheduled": 0,
        "queue_failed": 0,
        "queue_total": 0,
        "batch_planned": 0,
        "batch_uploaded": 0,
        "batch_failed": 0,
        "batch_last_error": None,
    }
    try:
        from ..db.repositories import publish_queue as publish_queue_repo

        pipe_ai_settings, config_hash = await ai_settings_repo.current_config_hash(pipeline_id)
        ai_enabled = pipe_ai_settings.get("enabled", True)
        counts = await reels.pipeline_reel_ai_counts(
            pipeline_id, config_hash if ai_enabled else None
        )
        inv = counts["inventory"]
        ai_stats = counts["ai"]
        ai_ready = int(ai_stats.get("ready", 0)) if ai_enabled else 0
        queue_stats = await publish_queue_repo.get_pipeline_queue_stats(pipeline_id)
        return {
            **fallback,
            "inventory_total": inv.get("total", 0),
            "ai_generated": ai_stats.get("generated", 0),
            "ai_pending": ai_stats.get("pending", 0),
            "ai_failed": ai_stats.get("failed", 0),
            "ai_ready": ai_ready,
            "queue_queued": queue_stats.get("queued", 0),
            "queue_processing": queue_stats.get("processing", 0),
            "queue_scheduled": queue_stats.get("scheduled", 0),
            "queue_failed": queue_stats.get("failed", 0),
            "queue_total": queue_stats.get("total", 0),
            "batch_planned": (batch or {}).get("planned_count", 0) or 0,
            "batch_uploaded": (batch or {}).get("uploaded_count", 0) or 0,
            "batch_failed": (batch or {}).get("failed_count", 0) or 0,
            "batch_last_error": (batch or {}).get("last_error"),
        }
    except Exception:
        return fallback