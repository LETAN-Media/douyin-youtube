from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PublishQueue, QueueStatus
from ...utils import gen_id
from ...db.session import is_postgres


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expired(now: datetime, ttl: int = 300) -> datetime:
    return now - timedelta(seconds=ttl)


READY_STATUSES = [QueueStatus.PENDING, QueueStatus.SCHEDULED]


async def enqueue(
    session: AsyncSession,
    *,
    pipeline_id: str,
    youtube_video_id: str,
    facebook_page_id: str,
    media_file_id: str,
    publish_mode: str = "reeels_or_video" if False else "reeels_or_video",
    ai_caption: str | None = None,
    ai_enhanced: bool = False,
    title: str | None = None,
    description: str | None = None,
    scheduled_for: datetime | None = None,
    priority: int = 0,
    schedule_id: str | None = None,
) -> PublishQueue:
    from ..models import PublishMode
    item = PublishQueue(
        id=gen_id("pq"),
        pipeline_id=pipeline_id,
        youtube_video_id=youtube_video_id,
        facebook_page_id=facebook_page_id,
        media_file_id=media_file_id,
        publish_mode=publish_mode,
        ai_caption=ai_caption,
        ai_enhanced=ai_enhanced,
        title=title,
        description=description,
        scheduled_for=scheduled_for,
        priority=priority,
        schedule_id=schedule_id,
        status=QueueStatus.SCHEDULED if scheduled_for else QueueStatus.PENDING,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def claim_next(
    session: AsyncSession,
    pipeline_id: str,
    worker_id: str,
    concurrency: int = 1,
    stale_ttl: int = 300,
    now: datetime | None = None,
) -> Sequence[PublishQueue]:
    if now is None:
        now = _now()
    expired = _expired(now, stale_ttl)
    ready = and_(
        PublishQueue.status.in_(READY_STATUSES),
        PublishQueue.scheduled_for.is_(None) | (PublishQueue.scheduled_for <= now),
        PublishQueue.reservation_expires_at.is_(None) | (PublishQueue.reservation_expires_at < expired),
    )
    stmt = (
        select(PublishQueue)
        .where(PublishQueue.pipeline_id == pipeline_id, ready)
        .order_by(PublishQueue.priority.desc(), PublishQueue.scheduled_for, PublishQueue.created_at)
        .limit(concurrency)
    )
    if is_postgres():
        stmt = stmt.with_for_update(skip_locked=True)
    result = await session.execute(stmt)
    rows = result.scalars().unique().all()
    token = gen_id("worker")
    for row in rows:
        row.status = QueueStatus.PROCESSING
        row.reservation_token = token
        row.reservation_expires_at = now + timedelta(seconds=stale_ttl)
        row.started_at = row.started_at or now
    await session.commit()
    for row in rows:
        await session.refresh(row)
    return rows


async def set_queue_status(session: AsyncSession, queue_item_id: str, status: str, **fields) -> PublishQueue | None:
    item = await session.get(PublishQueue, queue_item_id)
    if item is None:
        return None
    item.status = status
    for key, value in fields.items():
        if value is not None:
            setattr(item, key, value)
    if status in (QueueStatus.PUBLISHED, QueueStatus.FAILED, QueueStatus.CANCELLED):
        item.completed_at = _now()
        item.reservation_token = None
        item.reservation_expires_at = None
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def get_queue_item(session: AsyncSession, queue_item_id: str) -> PublishQueue | None:
    return await session.get(PublishQueue, queue_item_id)


async def list_queue(session: AsyncSession, pipeline_id: str, limit: int = 100, offset: int = 0, status: str | None = None) -> Sequence[PublishQueue]:
    stmt = select(PublishQueue).where(PublishQueue.pipeline_id == pipeline_id)
    if status:
        stmt = stmt.where(PublishQueue.status == status)
    result = await session.execute(stmt.order_by(PublishQueue.priority.desc(), PublishQueue.created_at).limit(limit).offset(offset))
    return result.scalars().all()


async def is_already_queued(session: AsyncSession, pipeline_id: str, youtube_video_id: str, facebook_page_id: str) -> bool:
    result = await session.execute(
        select(PublishQueue).where(
            PublishQueue.pipeline_id == pipeline_id,
            PublishQueue.youtube_video_id == youtube_video_id,
            PublishQueue.facebook_page_id == facebook_page_id,
            PublishQueue.status.in_([QueueStatus.PENDING, QueueStatus.SCHEDULED, QueueStatus.PROCESSING]),
        )
    )
    return result.scalars().first() is not None


async def count_scheduled_in_window(session: AsyncSession, pipeline_id: str, window_start, window_end) -> int:
    clause = PublishQueue.pipeline_id == pipeline_id
    if window_start is not None:
        clause = and_(clause, PublishQueue.scheduled_for >= window_start)
    if window_end is not None:
        clause = and_(clause, PublishQueue.scheduled_for <= window_end)
    result = await session.execute(
        select(func.count()).where(clause, PublishQueue.status.in_([QueueStatus.PENDING, QueueStatus.SCHEDULED]))
    )
    return result.scalar_one()


async def count_by_status(session: AsyncSession, pipeline_id: str, status: str) -> int:
    result = await session.execute(
        select(func.count())
        .where(PublishQueue.pipeline_id == pipeline_id, PublishQueue.status == status)
    )
    return result.scalar_one()

