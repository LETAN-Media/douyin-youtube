import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import DouyinSource, DouyinVideo, Pipeline, VideoJob


logger = logging.getLogger("douyin-youtube-scheduler")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_pipeline_local_now(pipeline: Pipeline) -> datetime:
    tz_name = pipeline.timezone or "UTC"
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc

    return datetime.now(tz)


def get_local_day_bounds(pipeline: Pipeline, now: datetime | None = None) -> tuple[datetime, datetime]:
    local_now = now or get_pipeline_local_now(pipeline)
    tz_name = pipeline.timezone or "UTC"
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
    pipeline: Pipeline,
    now: datetime,
) -> datetime | None:
    slots = pipeline.upload_slots or ["08:00", "11:00", "14:00", "17:00", "20:00", "23:00"]
    if not slots:
        return None

    tz_name = pipeline.timezone or "UTC"
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


def get_slot_type(slot_index: int, pipeline: Pipeline) -> str:
    backlog_count = pipeline.backlog_slots_per_day or 4
    new_count = pipeline.new_slots_per_day or 2
    total = max(backlog_count + new_count, 1)
    normalized = slot_index % total
    if normalized < backlog_count:
        return "backlog"
    return "new"


def _try_pick_video(
    db: Session,
    pipeline: Pipeline,
    slot_type: str,
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
    for i in range(len(sources)):
        idx = (cursor + i) % len(sources)
        source = sources[idx]

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

        if (pipeline.backlog_order or "asc").lower() == "desc":
            query = query.order_by(DouyinVideo.douyin_created_at.desc())
        else:
            query = query.order_by(DouyinVideo.douyin_created_at.asc())

        video = db.execute(query.limit(1)).scalar_one_or_none()
        if video is not None:
            pipeline.source_selection_cursor = (idx + 1) % len(sources)
            return video

    return None


def pick_video(
    db: Session,
    pipeline: Pipeline,
    slot_type: str,
) -> DouyinVideo | None:
    video = _try_pick_video(db, pipeline, slot_type)
    if video is not None:
        return video

    other_type = "new" if slot_type == "backlog" else "backlog"
    return _try_pick_video(db, pipeline, other_type)


def count_todays_released_jobs(db: Session, pipeline: Pipeline, local_day_start_utc: datetime) -> int:
    today_start = local_day_start_utc
    today_end = today_start + timedelta(days=1)

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


def schedule_for_pipeline(
    db: Session,
    pipeline: Pipeline,
    now: datetime | None = None,
) -> None:
    if now is None:
        now = utcnow()

    slots = pipeline.upload_slots or ["08:00", "11:00", "14:00", "17:00", "20:00", "23:00"]
    if not slots:
        return

    next_slot = get_next_upload_slot(pipeline, now)
    if next_slot is None:
        return

    if not (next_slot <= now < next_slot + timedelta(minutes=10)):
        logger.info(
            "Pipeline %s next slot %s, outside grace window",
            pipeline.id,
            next_slot,
        )
        return

    local_day_start_utc, _ = get_local_day_bounds(pipeline, now)
    today_released = count_todays_released_jobs(db, pipeline, local_day_start_utc)

    if today_released >= pipeline.daily_upload_limit:
        logger.info(
            "Pipeline %s reached daily limit %s/%s",
            pipeline.id,
            today_released,
            pipeline.daily_upload_limit,
        )
        return

    slot_index = next_slot.hour * 60 + next_slot.minute
    slot_type = get_slot_type(slot_index, pipeline)

    video = pick_video(db, pipeline, slot_type)
    if video is None:
        logger.info(
            "Pipeline %s has no available videos for %s slot",
            pipeline.id,
            slot_type,
        )
        return

    slot_key = next_slot.isoformat()

    job = VideoJob(
        source_url=video.url,
        source_title=video.title,
        title=None,
        description=video.description,
        privacy_status=pipeline.default_privacy,
        status="pending",
        pipeline_id=pipeline.id,
        source_video_id=video.video_id,
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
            "Pipeline %s slot %s already claimed, skipping",
            pipeline.id,
            slot_key,
        )
        return

    logger.info(
        "Scheduled video %s for pipeline %s at slot %s",
        video.video_id,
        pipeline.id,
        next_slot,
    )


def run_scheduler_once() -> None:
    with SessionLocal.begin() as db:
        pipelines = db.execute(
            select(Pipeline)
            .where(Pipeline.enabled == True)  # noqa: E712
        ).scalars().all()

        for pipeline in pipelines:
            try:
                schedule_for_pipeline(db, pipeline)
            except Exception:
                logger.exception(
                    "Failed to schedule pipeline %s",
                    pipeline.id,
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
