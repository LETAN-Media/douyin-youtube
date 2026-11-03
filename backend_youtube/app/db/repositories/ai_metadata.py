from __future__ import annotations

from datetime import datetime
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AIMetadata, AIStrategy
from ...utils import gen_id


async def upsert_ai_metadata(
    session: AsyncSession,
    pipeline_id: str,
    youtube_video_id: str,
    *,
    strategy: str = AIStrategy.AUTO,
    model: str | None = None,
    enhanced: bool = False,
    caption: str | None = None,
    hashtags: list[str] | None = None,
    title_suggestion: str | None = None,
    description_suggestion: str | None = None,
    raw_response: dict | None = None,
    error: str | None = None,
) -> AIMetadata:
    existing = (
        (await session.execute(
            select(AIMetadata).where(
                AIMetadata.pipeline_id == pipeline_id,
                AIMetadata.youtube_video_id == youtube_video_id,
            )
        )).scalars().first()
    )
    if existing is None:
        row = AIMetadata(
            id=gen_id("ai"),
            pipeline_id=pipeline_id,
            youtube_video_id=youtube_video_id,
            strategy=strategy,
            model=model,
            enhanced=enhanced,
            caption=caption,
            hashtags=hashtags,
            title_suggestion=title_suggestion,
            description_suggestion=description_suggestion,
            raw_response=raw_response,
            error=error,
        )
        session.add(row)
    else:
        existing.strategy = strategy
        existing.model = model or existing.model
        existing.enhanced = enhanced
        existing.caption = caption if caption is not None else existing.caption
        existing.hashtags = hashtags if hashtags is not None else existing.hashtags
        existing.title_suggestion = title_suggestion if title_suggestion is not None else existing.title_suggestion
        existing.description_suggestion = description_suggestion if description_suggestion is not None else existing.description_suggestion
        existing.raw_response = raw_response or existing.raw_response
        existing.error = error if error is not None else existing.error
        row = existing
    await session.flush()
    return row


async def get_ai_metadata(session: AsyncSession, pipeline_id: str, youtube_video_id: str) -> AIMetadata | None:
    result = await session.execute(
        select(AIMetadata).where(
            AIMetadata.pipeline_id == pipeline_id,
            AIMetadata.youtube_video_id == youtube_video_id,
        )
    )
    return result.scalars().first()


async def get_ai_metadata_pending(session: AsyncSession, pipeline_id: str, limit: int = 10) -> Sequence[AIMetadata]:
    result = await session.execute(
        select(AIMetadata).where(
            AIMetadata.pipeline_id == pipeline_id,
            AIMetadata.caption.is_(None),
            AIMetadata.error.is_(None),
        ).order_by(AIMetadata.created_at).limit(limit)
    )
    return result.scalars().all()


async def count_ai_metadata(session: AsyncSession, pipeline_id: str) -> int:
    result = await session.execute(
        select(func.count()).where(AIMetadata.pipeline_id == pipeline_id)
    )
    return result.scalar_one()
