from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import YouTubeVideo


async def upsert_video(
    session: AsyncSession,
    pipeline_id: str,
    video_id: str,
    *,
    channel_id: str | None = None,
    title: str | None = None,
    description: str | None = None,
    duration_seconds: int | None = None,
    publish_time=None,
    thumbnail_url: str | None = None,
    view_count: int | None = None,
    like_count: int | None = None,
    tags: list | None = None,
    raw: dict | None = None,
    is_insert_only: bool = False,
) -> YouTubeVideo:
    if is_insert_only:
        existing = await session.get(YouTubeVideo, video_id)
        if existing is not None:
            if raw:
                existing.raw = raw
                await session.flush()
            return existing
        video = YouTubeVideo(
            pipeline_id=pipeline_id,
            video_id=video_id,
            channel_id=channel_id,
            title=title,
            description=description,
            duration_seconds=duration_seconds,
            publish_time=publish_time,
            thumbnail_url=thumbnail_url,
            view_count=view_count,
            like_count=like_count,
            tags=tags,
            raw=raw,
        )
        session.add(video)
        try:
            await session.flush()
        except Exception:
            await session.rollback()
            existing = await session.get(YouTubeVideo, video_id)
            if existing is not None:
                if raw:
                    existing.raw = raw
                    await session.flush()
                return existing
            session.add(video)
            await session.flush()
        return video
    video = await session.get(YouTubeVideo, video_id)
    if video is None:
        video = YouTubeVideo(
            pipeline_id=pipeline_id, video_id=video_id, channel_id=channel_id, title=title,
            description=description, duration_seconds=duration_seconds, publish_time=publish_time,
            thumbnail_url=thumbnail_url, view_count=view_count, like_count=like_count, tags=tags, raw=raw,
        )
        session.add(video)
    else:
        video.channel_id = channel_id or video.channel_id
        video.title = title or video.title
        video.description = description or video.description
        video.duration_seconds = duration_seconds if duration_seconds is not None else video.duration_seconds
        video.publish_time = publish_time or video.publish_time
        video.thumbnail_url = thumbnail_url or video.thumbnail_url
        video.view_count = view_count if view_count is not None else video.view_count
        video.like_count = like_count if like_count is not None else video.like_count
        video.tags = tags if tags is not None else video.tags
        video.raw = raw or video.raw
    await session.flush()
    return video


async def get_video(session: AsyncSession, video_id: str) -> YouTubeVideo | None:
    return await session.get(YouTubeVideo, video_id)


async def list_videos(session: AsyncSession, pipeline_id: str, limit: int = 100, offset: int = 0) -> Sequence[YouTubeVideo]:
    result = await session.execute(select(YouTubeVideo).where(YouTubeVideo.pipeline_id == pipeline_id).order_by(YouTubeVideo.created_at.desc()).limit(limit).offset(offset))
    return result.scalars().all()
