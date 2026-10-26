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

    Slots are returned as ``HH:MM`` strings.
    """
    slots: list[str] = []
    parts = batch_time.split(":")
    start_hour = int(parts[0])
    start_minute = int(parts[1]) if len(parts) > 1 else 0

    for i in range(max_daily):
        total_minutes = (start_hour * 60 + start_minute) + i * (1440 // max_daily)
        h = (total_minutes // 60) % 24
        m = total_minutes % 60
        slots.append(f"{h:02d}:{m:02d}")
    return slots


async def generate_week_schedule(pipeline_id: str, max_daily: int = 5,
                                 batch_time: str = "06:00") -> dict:
    """Populate schedule slots for all 7 weekdays."""
    schedule = await schedules.get_or_create_schedule(
        pipeline_id, max_daily=max_daily, batch_time=batch_time
    )
    schedule_id = schedule["id"]
    await schedules.ensure_slots(schedule_id)

    # Enable evenly-spaced slots per weekday
    for weekday in range(7):
        slots = generate_daily_slots(
            datetime.now(timezone.utc), max_daily, batch_time
        )
        existing = await schedules.list_slots(schedule_id)
        for slot in existing:
            if slot["weekday"] == weekday:
                enabled = slot["slot_time"] in slots
                await schedules.set_slot_enabled(schedule_id, weekday, slot["slot_time"], enabled)
    return await schedules.get_by_pipeline(pipeline_id)
