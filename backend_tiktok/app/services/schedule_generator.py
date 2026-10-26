"""Schedule generation for weekly publish slots."""

import logging
from datetime import datetime, timedelta, timezone

from ..db.repositories import schedules

logger = logging.getLogger("backend-tiktok.services.schedule_generator")


def generate_daily_slots(
    start_date: datetime,
    max_daily: int,
    batch_time: str = "06:00",
    tz_offset_hours: int = 0,
) -> list[str]:
    """Generate ``max_daily`` evenly-spaced slot times for one day.

    Slots are returned as sorted ``HH:MM`` strings.
    """
    slots: list[str] = []
    parts = batch_time.split(":")
    start_hour = int(parts[0])
    start_minute = int(parts[1]) if len(parts) > 1 else 0

    max_daily = max(1, min(10, int(max_daily)))
    interval = 1440 // max_daily

    for i in range(max_daily):
        total_minutes = (start_hour * 60 + start_minute) + i * interval
        h = (total_minutes // 60) % 24
        m = total_minutes % 60
        slots.append(f"{h:02d}:{m:02d}")
    return sorted(slots)


async def generate_week_schedule(
    pipeline_id: str,
    max_daily: int = 5,
    batch_time: str = "06:00",
) -> dict:
    """Populate schedule slots for all 7 weekdays."""
    max_daily = max(1, min(10, int(max_daily)))
    schedule = await schedules.get_or_create_schedule(
        pipeline_id, max_daily=max_daily, batch_time=batch_time
    )
    schedule_id = schedule["id"]

    for weekday in range(7):
        slots = generate_daily_slots(
            datetime.now(timezone.utc), max_daily, batch_time
        )
        await schedules.sync_weekday_slots(schedule_id, weekday, slots)

    return await schedules.get_by_pipeline(pipeline_id)
