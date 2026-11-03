from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Pipeline, PublishSchedule
from ...utils import gen_id


def _today(tz) -> str:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d")


async def generate_day_schedule(session: AsyncSession, pipeline: Pipeline, date_str: str) -> Sequence[PublishSchedule]:
    existing = await session.execute(
        select(PublishSchedule).where(
            PublishSchedule.pipeline_id == pipeline.id,
            PublishSchedule.scheduled_date == date_str,
        )
    )
    if existing.scalars().first() is not None:
        return (await session.execute(
            select(PublishSchedule).where(
                PublishSchedule.pipeline_id == pipeline.id,
                PublishSchedule.scheduled_date == date_str,
            ).order_by(PublishSchedule.slot_index)
        )).scalars().all()
    slots = pipeline.publish_slots or []
    window = pipeline.slot_window_minutes
    max_daily = pipeline.slot_max_daily
    new_rows = []
    from zoneinfo import ZoneInfo
    base_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=ZoneInfo(pipeline.timezone))
    for idx, slot in enumerate(slots):
        if idx >= max_daily:
            break
        parts = slot.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        slot_time = f"{hour:02d}:{minute:02d}"
        row = PublishSchedule(
            id=gen_id("sched"),
            pipeline_id=pipeline.id,
            scheduled_date=date_str,
            slot_index=idx,
            slot_time=slot_time,
            slot_max_daily=max_daily,
        )
        session.add(row)
        new_rows.append(row)
    if not new_rows and not slots:
        now_utc = datetime.now(timezone.utc)
        row = PublishSchedule(
            id=gen_id("sched"),
            pipeline_id=pipeline.id,
            scheduled_date=date_str,
            slot_index=0,
            slot_time=(now_utc + timedelta(days=1)).strftime("%H:%M"),
            slot_max_daily=max_daily,
        )
        session.add(row)
        new_rows.append(row)
    await session.commit()
    for row in new_rows:
        await session.refresh(row)
    return new_rows


async def reserve_slot(session: AsyncSession, pipeline_id: str, date_str: str) -> PublishSchedule | None:
    result = await session.execute(
        select(PublishSchedule)
        .where(
            PublishSchedule.pipeline_id == pipeline_id,
            PublishSchedule.scheduled_date == date_str,
            PublishSchedule.publish_count < PublishSchedule.slot_max_daily,
        )
        .order_by(PublishSchedule.slot_index)
    )
    slot = result.scalars().first()
    if slot is None:
        return None
    slot.reserved_count += 1
    await session.commit()
    await session.refresh(slot)
    return slot


async def increment_slot_count(session: AsyncSession, slot_id: str) -> PublishSchedule | None:
    slot = await session.get(PublishSchedule, slot_id)
    if slot is None:
        return None
    slot.publish_count += 1
    await session.commit()
    await session.refresh(slot)
    return slot


async def release_slot_reservation(session: AsyncSession, slot_id: str) -> PublishSchedule | None:
    slot = await session.get(PublishSchedule, slot_id)
    if slot is None:
        return None
    slot.reserved_count = max(0, slot.reserved_count - 1)
    await session.commit()
    await session.refresh(slot)
    return slot


async def get_schedule_for_date(session: AsyncSession, pipeline_id: str, date_str: str) -> Sequence[PublishSchedule]:
    result = await session.execute(
        select(PublishSchedule).where(
            PublishSchedule.pipeline_id == pipeline_id,
            PublishSchedule.scheduled_date == date_str,
        ).order_by(PublishSchedule.slot_index)
    )
    return result.scalars().all()
