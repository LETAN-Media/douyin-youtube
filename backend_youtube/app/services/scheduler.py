import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..db.repositories import pipelines as pipeline_repo
from ..db.repositories import quota as quota_repo
from ..db.repositories import schedules as sched_repo
from ..db.repositories import queue as queue_repo
from ..db.repositories.schedules import generate_day_schedule

logger = logging.getLogger("backend-youtube.scheduler")


def today_str(tz_name: str, now: datetime | None = None) -> str:
    now = now or datetime.now(tz=ZoneInfo(tz_name))
    return now.strftime("%Y-%m-%d")


def _slot_datetime(slot_time: str, tz_name: str, date_str: str) -> datetime:
    parts = slot_time.split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    day_part = datetime.strptime(date_str, "%Y-%m-%d")
    base = day_part.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return base.replace(tzinfo=ZoneInfo(tz_name))


async def ensure_today_schedule(session, pipeline_id: str, now: datetime | None = None) -> list:
    pipeline = await pipeline_repo.get_pipeline(session, pipeline_id)
    if pipeline is None:
        return []
    now = now or datetime.now(tz=ZoneInfo(pipeline.timezone))
    date_str = now.strftime("%Y-%m-%d")
    rows = await sched_repo.get_schedule_for_date(session, pipeline_id, date_str)
    if rows:
        return rows
    return await generate_day_schedule(session, pipeline, date_str)


async def can_publish_today(session, pipeline, now: datetime | None = None) -> bool:
    now = now or datetime.now(tz=ZoneInfo(pipeline.timezone))
    date_str = now.strftime("%Y-%m-%d")
    return await quota_repo.can_publish_today(session, pipeline.id, date_str, pipeline.slot_max_daily)


async def count_scheduled_in_window(session, pipeline_id: str, window_start, window_end) -> int:
    if window_start is None and window_end is None:
        return 0
    start = window_start.astimezone(ZoneInfo("UTC")) if window_start is not None and hasattr(window_start, "astimezone") else window_start
    end = window_end.astimezone(ZoneInfo("UTC")) if window_end is not None and hasattr(window_end, "astimezone") else window_end
    return await queue_repo.count_scheduled_in_window(session, pipeline_id, start, end)


async def next_available_slot(session, pipeline, now: datetime | None = None):
    from ..db.models import QueueStatus
    now = now or datetime.now(tz=ZoneInfo(pipeline.timezone))
    if not pipeline.auto_publish or pipeline.status in ("paused", "draft"):
        return None
    if not await can_publish_today(session, pipeline, now):
        return None
    date_str = now.strftime("%Y-%m-%d")
    slots = await sched_repo.get_schedule_for_date(session, pipeline.id, date_str)
    if not slots:
        slots = await generate_day_schedule(session, pipeline, date_str)
    for slot in sorted(slots, key=lambda s: s.slot_index):
        if slot.publish_count >= slot.slot_max_daily:
            continue
        slot_dt = _slot_datetime(slot.slot_time, pipeline.timezone, date_str)
        if slot_dt < now:
            continue
        return slot_dt, slot
    return None


async def schedule_pending_items(session, pipeline, now: datetime | None = None) -> int:
    """Assign future publish times to eligible pending items based on slots."""
    from ..db.repositories.queue import list_queue, set_queue_status
    from ..db.repositories import schedules as srepo
    from ..db.models import QueueStatus
    now = now or datetime.now(tz=ZoneInfo(pipeline.timezone))
    if not pipeline.auto_publish or pipeline.status in ("paused", "draft"):
        return 0
    pending = await list_queue(session, pipeline.id, limit=500, status=QueueStatus.PENDING)
    scheduled = 0
    for item in pending:
        result = await next_available_slot(session, pipeline, now)
        if result is None:
            break
        slot_dt, slot = result
        if slot:
            await srepo.increment_slot_count(session, slot.id)
        await set_queue_status(session, item.id, QueueStatus.SCHEDULED, scheduled_for=slot_dt)
        scheduled += 1
    return scheduled


async def release_expired_reservation(session, claim_ttl_seconds: int = 300) -> None:
    return None
