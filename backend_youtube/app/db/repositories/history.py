from datetime import datetime, timedelta
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PublicationAttempt, PublicationHistory, PublicationOutcome
from ...utils import gen_id


def _apply_fields(row, fields: dict) -> None:
    for key, value in fields.items():
        if value is not None:
            setattr(row, key, value)


async def create_publication_history(
    session: AsyncSession,
    *,
    pipeline_id: str,
    youtube_video_id: str,
    facebook_page_id: str,
    media_file_id: str | None = None,
    facebook_post_id: str | None = None,
    facebook_video_id: str | None = None,
    facebook_reel_id: str | None = None,
    publish_mode: str = "reels_or_video",
    status: str = PublicationOutcome.SUCCESS,
    ai_caption: str | None = None,
    ai_enhanced: bool = False,
    title: str | None = None,
    description: str | None = None,
    duration_seconds: int | None = None,
    file_size_bytes: int | None = None,
    error: str | None = None,
    error_code: str | None = None,
    published_at: datetime | None = None,
    is_update: bool = False,
) -> PublicationHistory:
    if is_update:
        existing = await session.execute(
            select(PublicationHistory)
            .where(
                PublicationHistory.pipeline_id == pipeline_id,
                PublicationHistory.youtube_video_id == youtube_video_id,
                PublicationHistory.facebook_page_id == facebook_page_id,
            )
            .order_by(PublicationHistory.created_at.desc())
            .limit(1)
        )
        row = existing.scalars().first()
        if row is None:
            row = PublicationHistory(
                id=gen_id("pub"),
                pipeline_id=pipeline_id,
                youtube_video_id=youtube_video_id,
                facebook_page_id=facebook_page_id,
            )
            session.add(row)
            await session.flush()
        _apply_fields(row, dict(
            media_file_id=media_file_id, facebook_post_id=facebook_post_id,
            facebook_video_id=facebook_video_id, facebook_reel_id=facebook_reel_id,
            publish_mode=publish_mode, status=status, ai_caption=ai_caption,
            ai_enhanced=ai_enhanced, title=title, description=description,
            duration_seconds=duration_seconds, file_size_bytes=file_size_bytes,
            error=error, error_code=error_code, published_at=published_at or row.published_at,
        ))
        await session.commit()
        await session.refresh(row)
        return row
    row = PublicationHistory(
        id=gen_id("pub"),
        pipeline_id=pipeline_id,
        youtube_video_id=youtube_video_id,
        facebook_page_id=facebook_page_id,
        media_file_id=media_file_id,
        facebook_post_id=facebook_post_id,
        facebook_video_id=facebook_video_id,
        facebook_reel_id=facebook_reel_id,
        publish_mode=publish_mode,
        status=status,
        ai_caption=ai_caption,
        ai_enhanced=ai_enhanced,
        title=title,
        description=description,
        duration_seconds=duration_seconds,
        file_size_bytes=file_size_bytes,
        error=error,
        error_code=error_code,
        published_at=published_at,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def is_already_published(session: AsyncSession, pipeline_id: str, youtube_video_id: str, facebook_page_id: str) -> bool:
    result = await session.execute(
        select(PublicationHistory).where(
            PublicationHistory.pipeline_id == pipeline_id,
            PublicationHistory.youtube_video_id == youtube_video_id,
            PublicationHistory.facebook_page_id == facebook_page_id,
            PublicationHistory.status == PublicationOutcome.SUCCESS,
        )
    )
    return result.scalars().first() is not None


async def list_publications(session: AsyncSession, pipeline_id: str, limit: int = 100, offset: int = 0) -> Sequence[PublicationHistory]:
    result = await session.execute(
        select(PublicationHistory).where(PublicationHistory.pipeline_id == pipeline_id).order_by(PublicationHistory.created_at.desc()).limit(limit).offset(offset)
    )
    return result.scalars().all()


async def create_publication_attempt(
    session: AsyncSession,
    *,
    pipeline_id: str,
    queue_item_id: str,
    facebook_page_id: str,
    attempt_number: int,
    publish_mode: str,
    status: str,
    facebook_post_id: str | None = None,
    facebook_reel_id: str | None = None,
    facebook_video_id: str | None = None,
    error: str | None = None,
    error_code: str | None = None,
    request_payload: dict | None = None,
    response_payload: dict | None = None,
    completed_at: datetime | None = None,
) -> PublicationAttempt:
    row = PublicationAttempt(
        id=gen_id("pa"),
        pipeline_id=pipeline_id,
        queue_item_id=queue_item_id,
        facebook_page_id=facebook_page_id,
        attempt_number=attempt_number,
        publish_mode=publish_mode,
        status=status,
        facebook_post_id=facebook_post_id,
        facebook_reel_id=facebook_reel_id,
        facebook_video_id=facebook_video_id,
        error=error,
        error_code=error_code,
        request_payload=request_payload,
        response_payload=response_payload,
        completed_at=completed_at,
    )
    session.add(row)
    await session.flush()
    return row


async def list_attempts_for_queue(session: AsyncSession, queue_item_id: str) -> Sequence[PublicationAttempt]:
    result = await session.execute(
        select(PublicationAttempt).where(PublicationAttempt.queue_item_id == queue_item_id).order_by(PublicationAttempt.attempt_number)
    )
    return result.scalars().all()


async def count_today_published(session: AsyncSession, pipeline_id: str, date_str: str) -> int:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from ...config import settings
    tz = ZoneInfo(settings.SCHEDULER_SLOT_DEFAULT_TIMEZONE)
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)
    start = dt + timedelta(hours=0)
    end = start + timedelta(days=1)
    from sqlalchemy import func
    result = await session.execute(
        select(func.count())
        .where(
            PublicationHistory.pipeline_id == pipeline_id,
            PublicationHistory.created_at >= start,
            PublicationHistory.created_at < end,
        )
    )
    return result.scalar_one()
