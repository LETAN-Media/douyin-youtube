from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MediaFile, MediaPublishStatus, MediaStatus
from ...utils import gen_id


async def create_media_file(session: AsyncSession, pipeline_id: str, youtube_video_id: str, **fields) -> MediaFile:
    media = MediaFile(id=gen_id("media"), pipeline_id=pipeline_id, youtube_video_id=youtube_video_id, **fields)
    session.add(media)
    await session.commit()
    await session.refresh(media)
    return media


async def get_media_file(session: AsyncSession, media_id: str) -> MediaFile | None:
    return await session.get(MediaFile, media_id)


async def get_ready_media_for_video(session: AsyncSession, pipeline_id: str, youtube_video_id: str) -> MediaFile | None:
    result = await session.execute(
        select(MediaFile).where(
            MediaFile.pipeline_id == pipeline_id,
            MediaFile.youtube_video_id == youtube_video_id,
            MediaFile.publish_status == MediaPublishStatus.READY,
            MediaFile.status == MediaStatus.READY,
        ).order_by(MediaFile.created_at.desc())
    )
    return result.scalars().first()


async def update_media_status(session: AsyncSession, media_id: str, status: str, **fields) -> MediaFile | None:
    media = await session.get(MediaFile, media_id)
    if media is None:
        return None
    media.status = status
    for key, value in fields.items():
        if value is not None:
            setattr(media, key, value)
    session.add(media)
    await session.commit()
    await session.refresh(media)
    return media


async def mark_media_publish_status(session: AsyncSession, media_id: str, status: str) -> MediaFile | None:
    media = await session.get(MediaFile, media_id)
    if media is None:
        return None
    media.publish_status = status
    session.add(media)
    await session.commit()
    await session.refresh(media)
    return media


async def list_media_for_video(session: AsyncSession, pipeline_id: str, youtube_video_id: str) -> Sequence[MediaFile]:
    result = await session.execute(
        select(MediaFile).where(
            MediaFile.pipeline_id == pipeline_id,
            MediaFile.youtube_video_id == youtube_video_id,
        ).order_by(MediaFile.created_at.desc())
    )
    return result.scalars().all()


async def list_media_by_status(session: AsyncSession, pipeline_id: str, status: str, limit: int = 100) -> Sequence[MediaFile]:
    result = await session.execute(
        select(MediaFile).where(
            MediaFile.pipeline_id == pipeline_id,
            MediaFile.status == status,
        ).order_by(MediaFile.created_at).limit(limit)
    )
    return result.scalars().all()


def is_media_ready(media: MediaFile) -> bool:
    return media.status == MediaStatus.READY and media.publish_status == MediaPublishStatus.READY and media.local_path is not None


async def cleanup_expired_media(session: AsyncSession, pipeline_id: str, older_than_seconds: int = 3600) -> int:
    from sqlalchemy import delete
    cutoff = datetime.now(timezone.utc) and None
    return 0
