import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import DouyinSource, DouyinVideo, Pipeline, VideoJob


logger = logging.getLogger("douyin-youtube-scheduler")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_next_upload_slot(
    pipeline: Pipeline,
    now: datetime,
) -> datetime | None:
    slots = pipeline.upload_slots or ["09:00", "13:00", "17:00", "21:00"]
    if not slots:
        return None

    today = now.date()
    candidates: list[datetime] = []

    for time_str in slots:
        try:
            hour, minute = map(int, time_str.split(":"))
        except ValueError:
            continue

        slot_time = datetime.combine(today, time(hour, minute))
        if slot_time.tzinfo is None:
            slot_time = slot_time.replace(tzinfo=timezone.utc)
        candidates.append(slot_time)

    candidates.sort()

    future = [slot for slot in candidates if slot >= now]
    if future:
        return future[0]

    tomorrow = today + timedelta(days=1)
    try:
        hour, minute = map(int, slots[0].split(":"))
    except ValueError:
        return None

    slot_time = datetime.combine(tomorrow, time(hour, minute))
    if slot_time.tzinfo is None:
        slot_time = slot_time.replace(tzinfo=timezone.utc)
    return slot_time


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


def schedule_for_pipeline(
    db: Session,
    pipeline: Pipeline,
) -> None:
    now = utcnow()

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_published = db.execute(
        select(func.count(VideoJob.id))
        .where(VideoJob.pipeline_id == pipeline.id)
        .where(VideoJob.status == "published")
        .where(VideoJob.created_at >= today_start)
    ).scalar_one_or_none()
    today_published = today_published or 0

    if today_published >= pipeline.daily_upload_limit:
        logger.info(
            "Pipeline %s reached daily limit %s/%s",
            pipeline.id,
            today_published,
            pipeline.daily_upload_limit,
        )
        return

    next_slot = get_next_upload_slot(pipeline, now)
    if next_slot is None or (next_slot - now) > timedelta(minutes=5):
        logger.info(
            "Pipeline %s next slot %s, not yet time",
            pipeline.id,
            next_slot,
        )
        return

    slot_cycle = max(pipeline.backlog_slots_per_day + pipeline.new_slots_per_day, 1)
    slot_index = today_published % slot_cycle
    if slot_index < pipeline.backlog_slots_per_day:
        slot_type = "backlog"
    else:
        slot_type = "new"

    video = pick_video(db, pipeline, slot_type)
    if video is None:
        logger.info(
            "Pipeline %s has no available videos for %s slot",
            pipeline.id,
            slot_type,
        )
        return

    job = VideoJob(
        source_url=video.url,
        source_title=video.title,
        title=None,
        description=video.description,
        privacy_status=pipeline.default_privacy,
        status="pending",
        pipeline_id=pipeline.id,
        source_video_id=video.video_id,
    )
    db.add(job)

    video.status = "scheduled"
    video.scheduled_at = now

    db.commit()
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
