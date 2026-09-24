import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import Destination, DouyinSource, DouyinVideo, Pipeline, Publication, VideoJob
from app.ai_metadata import evaluate_content_level


logger = logging.getLogger("douyin-youtube-scheduler")


# Scheduler skip-reason codes surfaced via scheduler-status for observability.
REASON_NOT_CONNECTED = "DESTINATION_NOT_CONNECTED"
REASON_NO_INVENTORY = "NO_AVAILABLE_INVENTORY"
REASON_DAILY_LIMIT = "DAILY_LIMIT_REACHED"
REASON_WAITING_SLOT = "WAITING_NEXT_SLOT"
REASON_DISABLED = "SCHEDULER_DISABLED"
REASON_WORKER_ERROR = "WORKER_ERROR"
REASON_UPLOAD_INTERVAL = "UPLOAD_INTERVAL_WAIT"
REASON_SOURCE_DAILY_LIMIT = "SOURCE_DAILY_LIMIT_REACHED"


def _keywords_hit(text: str, keywords: list[str] | None) -> bool:
    lowered = (text or "").lower()
    for kw in keywords or []:
        kw = (kw or "").strip().lower()
        if kw and kw in lowered:
            return True
    return False


def count_source_today(
    db: Session,
    source_id: str,
    day_start_utc: datetime,
) -> int:
    """AUTO publications (excl. failed/skipped) for a source since day start."""
    day_end = day_start_utc + timedelta(days=1)
    count = db.execute(
        select(func.count(Publication.id))
        .join(DouyinVideo, Publication.douyin_video_id == DouyinVideo.id)
        .where(DouyinVideo.source_id == source_id)
        .where(Publication.publication_mode == "auto")
        .where(Publication.created_at >= day_start_utc)
        .where(Publication.created_at < day_end)
        .where(Publication.status.notin_(["failed", "skipped"]))
    ).scalar_one_or_none()
    return int(count or 0)


def _source_daily_reached(
    db: Session,
    source: DouyinSource,
    day_start_utc: datetime,
) -> bool:
    try:
        limit = int(source.max_videos_per_day or 5)
    except (TypeError, ValueError):
        limit = 5
    if limit <= 0:
        return True
    return count_source_today(db, source.id, day_start_utc) >= limit


def _hold_video(
    db: Session,
    cand: DouyinVideo,
    *,
    level: str,
    reason: str,
) -> None:
    cand.status = "held"
    cand.match_level = level
    cand.hold_reason = reason[:2000]
    try:
        db.commit()
    except Exception:
        db.rollback()


def _reject_video(
    db: Session,
    cand: DouyinVideo,
    *,
    level: str,
    reason: str,
) -> None:
    cand.status = "rejected"
    cand.match_level = level
    cand.hold_reason = reason[:2000]
    try:
        db.commit()
    except Exception:
        db.rollback()


def _apply_keyword_action(
    db: Session,
    cand: DouyinVideo,
    source: DouyinSource,
    reason: str,
    *,
    policy: str,
    destination_id: str | None,
) -> None:
    """Route a keyword-filter hit through the matching verdict policy."""
    if policy == "mismatch":
        action = (source.mismatch_policy or "reject").lower()
    else:
        action = (source.borderline_policy or "hold").lower()
    logger.info(
        "Video %s keyword-filtered for destination %s: %s (action=%s)",
        cand.video_id,
        destination_id,
        reason,
        action,
    )
    cand.match_level = "mismatch" if policy == "mismatch" else "borderline"
    if action == "continue":
        return
    if action == "hold":
        _hold_video(db, cand, level=cand.match_level or policy, reason=reason)
    else:
        _reject_video(db, cand, level=cand.match_level or policy, reason=reason)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_local_now(timezone_name: str) -> datetime:
    tz_name = timezone_name or "UTC"
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    return datetime.now(tz)


def get_local_day_bounds(timezone_name: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    local_now = now or get_local_now(timezone_name)
    tz_name = timezone_name or "UTC"
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc

    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    local_end = local_start + timedelta(days=1)

    utc_start = local_start.astimezone(timezone.utc)
    utc_end = local_end.astimezone(timezone.utc)

    return utc_start, utc_end


def get_next_upload_slot(
    slots: list[str],
    timezone_name: str,
    now: datetime,
) -> datetime | None:
    slots = slots or ["08:00", "11:00", "14:00", "17:00", "20:00", "23:00"]
    if not slots:
        return None

    tz_name = timezone_name or "UTC"
    try:
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo(tz_name)
    except Exception:
        local_tz = timezone.utc

    local_now = now.astimezone(local_tz)
    today_local = local_now.date()

    candidates: list[datetime] = []

    for time_str in slots:
        try:
            hour, minute = map(int, time_str.split(":"))
        except ValueError:
            continue

        slot_local = datetime.combine(today_local, datetime.min.time().replace(hour=hour, minute=minute))
        slot_local = slot_local.replace(tzinfo=local_tz)
        slot_utc = slot_local.astimezone(timezone.utc)
        candidates.append(slot_utc)

    candidates.sort()

    for slot in candidates:
        if slot <= now < slot + timedelta(minutes=10):
            return slot

    future = [slot for slot in candidates if slot > now]
    if future:
        return future[0]

    tomorrow_local = today_local + timedelta(days=1)
    try:
        hour, minute = map(int, slots[0].split(":"))
    except ValueError:
        return None

    slot_local = datetime.combine(tomorrow_local, datetime.min.time().replace(hour=hour, minute=minute))
    slot_local = slot_local.replace(tzinfo=local_tz)
    return slot_local.astimezone(timezone.utc)


def _try_pick_video(
    db: Session,
    pipeline: Pipeline,
    slot_type: str,
    destination: Destination | None = None,
) -> DouyinVideo | None:
    sources = db.execute(
        select(DouyinSource)
        .where(DouyinSource.pipeline_id == pipeline.id)
        .where(DouyinSource.enabled == True)  # noqa: E712
        .order_by(DouyinSource.created_at.asc())
    ).scalars().all()

    if not sources:
        return None

    cursor = pipeline.source_selection_cursor or 0
    day_start_utc: datetime | None = None
    if destination is not None:
        try:
            day_start_utc, _ = get_local_day_bounds(
                destination.timezone or "UTC", utcnow()
            )
        except Exception:
            day_start_utc = None
    if day_start_utc is None:
        now_utc = utcnow()
        day_start_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

    for i in range(len(sources)):
        idx = (cursor + i) % len(sources)
        source = sources[idx]

        # Per-source daily AUTO limit.
        if _source_daily_reached(db, source, day_start_utc):
            logger.info(
                "Source %s reached daily AUTO limit %s",
                source.id,
                source.max_videos_per_day,
            )
            continue

        query = (
            select(DouyinVideo)
            .where(DouyinVideo.source_id == source.id)
            .where(DouyinVideo.pipeline_id == pipeline.id)
            .where(DouyinVideo.status.in_(["new", "backlog"]))
            .where(DouyinVideo.status != "published")
        )

        if slot_type == "backlog":
            query = query.where(DouyinVideo.is_backlog == True)  # noqa: E712
        else:
            query = query.where(DouyinVideo.is_backlog == False)  # noqa: E712

        # Source order overrides pipeline backlog_order (default oldest first).
        desc_order = (pipeline.backlog_order or "asc").lower() == "desc"
        if (source.order or "oldest_first").lower() == "newest_first":
            desc_order = True
        elif (source.order or "").lower() == "oldest_first":
            desc_order = False
        if desc_order:
            query = query.order_by(DouyinVideo.douyin_created_at.desc())
        else:
            query = query.order_by(DouyinVideo.douyin_created_at.asc())

        candidates = db.execute(query.limit(50)).scalars().all()
        for cand in candidates:
            # Check content_match if destination or pipeline requires it
            niche = destination.metadata_profile if destination else pipeline.niche
            prompt_override = destination.prompt_override if destination else None

            text = f"{cand.title or ''}\n{cand.description or ''}"

            # Source keyword filters act like verdicts.
            if _keywords_hit(text, source.exclude_keywords):
                reason = (
                    "KEYWORD_EXCLUDED: video matches source exclude_keywords"
                )
                _apply_keyword_action(
                    db, cand, source, reason, policy="mismatch",
                    destination_id=destination.id if destination else None,
                )
                continue
            if (source.include_keywords or []) and not _keywords_hit(
                text, source.include_keywords
            ):
                reason = (
                    "KEYWORD_MISSING: video matches none of source "
                    "include_keywords"
                )
                _apply_keyword_action(
                    db, cand, source, reason, policy="borderline",
                    destination_id=destination.id if destination else None,
                )
                continue

            level, match_reason = evaluate_content_level(
                text,
                niche=niche,
                prompt_override=prompt_override,
            )
            cand.match_level = level

            if level == "match":
                pipeline.source_selection_cursor = (idx + 1) % len(sources)
                return cand

            if level == "borderline":
                policy = (source.borderline_policy or "hold").lower()
                if policy == "continue":
                    logger.info(
                        "Video %s borderline but source %s policy=continue",
                        cand.video_id,
                        source.id,
                    )
                    pipeline.source_selection_cursor = (idx + 1) % len(sources)
                    return cand
                logger.info(
                    "Video %s held (borderline) for destination %s: %s",
                    cand.video_id,
                    destination.id if destination else None,
                    match_reason,
                )
                _hold_video(db, cand, level=level, reason=match_reason)
                continue

            # mismatch
            policy = (source.mismatch_policy or "reject").lower()
            if policy == "hold":
                logger.info(
                    "Video %s held (mismatch) for destination %s: %s",
                    cand.video_id,
                    destination.id if destination else None,
                    match_reason,
                )
                _hold_video(db, cand, level=level, reason=match_reason)
            else:
                logger.warning(
                    "Video %s (%s) rejected by AI content match for destination %s: %s",
                    cand.video_id,
                    cand.title,
                    destination.id if destination else None,
                    match_reason,
                )
                _reject_video(db, cand, level=level, reason=match_reason)
            continue

    return None


def pick_video(
    db: Session,
    pipeline: Pipeline,
    slot_type: str,
    destination: Destination | None = None,
) -> DouyinVideo | None:
    video = _try_pick_video(db, pipeline, slot_type, destination=destination)
    if video is not None:
        return video

    other_type = "new" if slot_type == "backlog" else "backlog"
    return _try_pick_video(db, pipeline, other_type, destination=destination)


def count_todays_released_jobs(
    db: Session,
    pipeline: Pipeline,
    local_day_start_utc: datetime,
    destination: Destination | None = None,
) -> int:
    """Per-destination daily count (preferred) with pipeline fallback.

    When destination is given, count Publications for that destination
    created today excluding failed/skipped. Otherwise legacy pipeline
    VideoJob count.
    """
    today_start = local_day_start_utc
    today_end = today_start + timedelta(days=1)

    if destination is not None:
        pub_count = db.execute(
            select(func.count(Publication.id))
            .where(Publication.destination_id == destination.id)
            .where(Publication.created_at >= today_start)
            .where(Publication.created_at < today_end)
            .where(Publication.status.notin_(["failed", "skipped"]))
        ).scalar_one_or_none()
        job_count = db.execute(
            select(func.count(VideoJob.id))
            .where(VideoJob.destination_id == destination.id)
            .where(VideoJob.created_at >= today_start)
            .where(VideoJob.created_at < today_end)
            .where(
                VideoJob.status.in_(
                    ["published", "pending", "downloading", "uploading"]
                )
            )
        ).scalar_one_or_none()
        # Each schedule creates 1 Publication + 1 Job; take max to be safe
        # against legacy rows missing one side.
        return int(max(int(pub_count or 0), int(job_count or 0)))

    count = db.execute(
        select(func.count(VideoJob.id))
        .where(VideoJob.pipeline_id == pipeline.id)
        .where(VideoJob.created_at >= today_start)
        .where(VideoJob.created_at < today_end)
        .where(
            VideoJob.status.in_(
                ["published", "pending", "downloading", "uploading"]
            )
        )
    ).scalar_one_or_none()

    return count or 0


def get_slot_type(slot_index: int, backlog_slots: int, new_slots: int) -> str:
    total = max(backlog_slots + new_slots, 1)
    normalized = slot_index % total
    if normalized < backlog_slots:
        return "backlog"
    return "new"


def count_inventory_available(db: Session, pipeline: Pipeline) -> int:
    count = db.execute(
        select(func.count(DouyinVideo.id))
        .where(DouyinVideo.pipeline_id == pipeline.id)
        .where(DouyinVideo.status.in_(["new", "backlog"]))
    ).scalar_one_or_none()
    return int(count or 0)


def is_destination_ready(
    destination: Destination,
) -> tuple[bool, str | None]:
    """Destination must be connected before any Publication/VideoJob is made."""
    if not destination.enabled:
        return False, REASON_DISABLED
    if (destination.platform or "").lower() != "youtube":
        return False, "UNSUPPORTED_PLATFORM"
    if not destination.connected:
        return False, REASON_NOT_CONNECTED
    if not destination.credentials:
        return False, REASON_NOT_CONNECTED
    return True, None


def _mark_destination_cycle(
    db: Session,
    destination: Destination,
    now: datetime,
    skip_reason: str | None,
    job_created: bool = False,
) -> None:
    try:
        destination.last_scheduler_check_at = now
        destination.last_cycle_at = now
        destination.last_skip_reason = skip_reason
        if job_created:
            destination.last_job_created_at = now
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


SLOT_GRACE_MINUTES = 10
CATCHUP_MAX_HOURS = 24


def _resolve_tz(timezone_name: str):
    tz_name = timezone_name or "UTC"
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz_name)
    except Exception:
        return timezone.utc


def get_slots_between(
    slots: list[str],
    timezone_name: str,
    start: datetime,
    end: datetime,
) -> list[datetime]:
    """Enumerate all upload slot datetimes (UTC) with start < slot <= end."""
    if not slots:
        return []
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if end <= start:
        return []
    local_tz = _resolve_tz(timezone_name)
    start_local = start.astimezone(local_tz)
    end_local = end.astimezone(local_tz)
    results: list[datetime] = []
    day = start_local.date()
    last_day = end_local.date()
    while day <= last_day:
        for time_str in slots:
            try:
                hour, minute = map(int, str(time_str).split(":"))
            except ValueError:
                continue
            try:
                slot_local = datetime.combine(
                    day, datetime.min.time().replace(hour=hour, minute=minute)
                ).replace(tzinfo=local_tz)
            except ValueError:
                continue
            slot_utc = slot_local.astimezone(timezone.utc)
            if start < slot_utc <= end:
                results.append(slot_utc)
        day = day + timedelta(days=1)
    results.sort()
    return results


def get_due_slots(
    slots: list[str],
    timezone_name: str,
    now: datetime,
    last_check: datetime | None,
    catchup_max_hours: int = CATCHUP_MAX_HOURS,
) -> list[datetime]:
    """Return due slots including catch-up for missed windows.

    - Normal steady state: only the current grace-window slot is due.
    - After sleep/restart: every slot in (last_check, now] is due (capped
      at catchup_max_hours, default 24h) plus the current grace slot.
    Deduplication is enforced by schedule_slot_key downstream.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    due: list[datetime] = []
    seen: set[str] = set()

    def _add(slot: datetime):
        key = slot.isoformat()
        if key not in seen:
            seen.add(key)
            due.append(slot)

    # Current grace-window slot always qualifies (if any).
    current = get_next_upload_slot(slots or [], timezone_name, now)
    if current is not None and (
        current <= now < current + timedelta(minutes=SLOT_GRACE_MINUTES)
    ):
        _add(current)

    if last_check is not None:
        if last_check.tzinfo is None:
            last_check = last_check.replace(tzinfo=timezone.utc)
        capped = max(last_check, now - timedelta(hours=catchup_max_hours))
        for slot in get_slots_between(slots or [], timezone_name, capped, now):
            _add(slot)
    elif current is None:
        pass

    due.sort()
    return due


def schedule_for_destination(
    db: Session,
    destination: Destination,
    now: datetime | None = None,
    catchup_max_hours: int = CATCHUP_MAX_HOURS,
) -> None:
    if now is None:
        now = utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if not destination.enabled:
        _mark_destination_cycle(db, destination, now, REASON_DISABLED)
        return

    pipeline = db.get(Pipeline, destination.pipeline_id)
    if pipeline is None or not pipeline.enabled:
        _mark_destination_cycle(db, destination, now, REASON_DISABLED)
        return

    # Destination must be connected before scheduling (no late worker fail).
    ready, reason = is_destination_ready(destination)
    if not ready:
        logger.warning(
            "destination_not_connected destination=%s platform=%s connected=%s",
            destination.id,
            destination.platform,
            destination.connected,
        )
        _mark_destination_cycle(
            db, destination, now, reason or REASON_NOT_CONNECTED
        )
        return

    slots = destination.upload_slots or ["08:00", "11:00", "14:00", "17:00", "20:00", "23:00"]
    if not slots:
        _mark_destination_cycle(db, destination, now, REASON_WAITING_SLOT)
        return

    last_check = destination.last_scheduler_check_at
    if last_check is not None and last_check.tzinfo is None:
        last_check = last_check.replace(tzinfo=timezone.utc)

    due_slots = get_due_slots(
        slots, destination.timezone, now, last_check, catchup_max_hours
    )

    if not due_slots:
        try:
            nxt = get_next_upload_slot(slots, destination.timezone, now)
            logger.info(
                "Destination %s next slot %s, outside grace window",
                destination.id,
                nxt,
            )
        except Exception:
            pass
        _mark_destination_cycle(db, destination, now, REASON_WAITING_SLOT)
        return

    local_day_start_utc, _ = get_local_day_bounds(destination.timezone, now)
    created_any = False

    for slot in due_slots:
        # Per-destination daily limit (checked before every slot).
        today_released = count_todays_released_jobs(
            db, pipeline, local_day_start_utc, destination
        )
        if today_released >= (destination.daily_upload_limit or 6):
            logger.info(
                "Destination %s reached daily limit %s/%s",
                destination.id,
                today_released,
                destination.daily_upload_limit,
            )
            _mark_destination_cycle(db, destination, now, REASON_DAILY_LIMIT)
            return

        # Minimum interval between YouTube uploads for this destination.
        try:
            min_interval = int(destination.min_upload_interval_minutes or 0)
        except (TypeError, ValueError):
            min_interval = 0
        if min_interval > 0:
            last_pub_at = db.execute(
                select(func.max(Publication.created_at))
                .where(Publication.destination_id == destination.id)
                .where(Publication.status.notin_(["failed", "skipped"]))
            ).scalar_one_or_none()
            ref = destination.last_job_created_at or last_pub_at
            if ref is not None:
                if ref.tzinfo is None:
                    ref = ref.replace(tzinfo=timezone.utc)
                elapsed = (now - ref).total_seconds()
                if elapsed < min_interval * 60:
                    logger.info(
                        "Destination %s upload interval wait %.0fs < %sm",
                        destination.id,
                        elapsed,
                        min_interval,
                    )
                    _mark_destination_cycle(
                        db, destination, now, REASON_UPLOAD_INTERVAL
                    )
                    return

        slot_index = slot.hour * 60 + slot.minute
        slot_type = get_slot_type(
            slot_index,
            destination.backlog_slots_per_day or 4,
            destination.new_slots_per_day or 2,
        )

        video = pick_video(db, pipeline, slot_type, destination=destination)
        if video is None:
            logger.warning(
                "NO_AVAILABLE_INVENTORY destination=%s slot=%s type=%s",
                destination.id,
                slot.isoformat(),
                slot_type,
            )
            _mark_destination_cycle(db, destination, now, REASON_NO_INVENTORY)
            return

        slot_key = f"{destination.id}:{slot.isoformat()}"

        # Idempotency: schedule_slot_key unique prevents duplicates after
        # restart / catch-up replays.
        existing = db.execute(
            select(VideoJob)
            .where(VideoJob.schedule_slot_key == slot_key)
            .limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            logger.info(
                "Destination %s slot %s already claimed, skipping",
                destination.id,
                slot_key,
            )
            continue

        publication = Publication(
            pipeline_id=pipeline.id,
            douyin_video_id=video.id,
            destination_id=destination.id,
            platform=destination.platform,
            status="scheduled",
            scheduled_at=slot,
        )
        db.add(publication)
        try:
            db.flush()  # assign publication.id for job link
        except IntegrityError:
            db.rollback()
            logger.info(
                "Destination %s publication already exists, skipping slot %s",
                destination.id,
                slot_key,
            )
            continue

        job = VideoJob(
            source_url=video.url,
            source_title=video.title,
            title=None,
            description=video.description,
            privacy_status=pipeline.default_privacy,
            status="pending",
            pipeline_id=pipeline.id,
            source_video_id=video.video_id,
            destination_id=destination.id,
            publication_id=publication.id,
            schedule_slot_key=slot_key,
        )
        db.add(job)

        video.status = "scheduled"
        video.scheduled_at = now

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            logger.info(
                "Destination %s slot %s already claimed, skipping",
                destination.id,
                slot_key,
            )
            continue

        created_any = True
        logger.info(
            "Scheduled video %s for destination %s at slot %s",
            video.video_id,
            destination.id,
            slot,
        )
        # Refresh day bounds in case catch-up spans midnight.
        local_day_start_utc, _ = get_local_day_bounds(
            destination.timezone, now
        )

    _mark_destination_cycle(
        db, destination, now, None if created_any else REASON_WAITING_SLOT,
        job_created=created_any,
    )


def schedule_for_pipeline(
    db: Session,
    pipeline: Pipeline,
    now: datetime | None = None,
) -> None:
    destination = db.execute(
        select(Destination)
        .where(Destination.pipeline_id == pipeline.id)
        .where(Destination.enabled == True)  # noqa: E712
        .limit(1)
    ).scalar_one_or_none()

    if destination is None:
        return

    schedule_for_destination(db, destination, now=now)


def run_scheduler_once() -> None:
    with SessionLocal() as db:
        destinations = db.execute(
            select(Destination)
            .where(Destination.enabled == True)  # noqa: E712
        ).scalars().all()

        # Detach ids first: schedule_for_destination commits per destination.
        dest_ids = [d.id for d in destinations]

        for dest_id in dest_ids:
            try:
                with SessionLocal() as ddb:
                    destination = ddb.get(Destination, dest_id)
                    if destination is None:
                        continue
                    # Reattach pipeline check inside schedule_for_destination.
                    schedule_for_destination(ddb, destination)
            except Exception:
                logger.exception(
                    "Failed to schedule destination %s",
                    dest_id,
                )


async def scheduler_loop() -> None:
    if not getattr(settings, "scheduler_enabled", True):
        logger.info("Douyin scheduler is disabled")
        return

    startup_delay = getattr(settings, "scheduler_startup_delay_seconds", 10)
    poll_interval = getattr(settings, "scheduler_poll_seconds", 60)

    logger.info("Douyin scheduler started, waiting %s seconds before first run", startup_delay)
    await asyncio.sleep(startup_delay)

    while True:
        try:
            logger.info("Starting scheduler cycle")
            await asyncio.to_thread(run_scheduler_once)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduler loop error")

        logger.info("Scheduler sleeping for %s seconds", poll_interval)
        await asyncio.sleep(poll_interval)
