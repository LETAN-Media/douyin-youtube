from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import YouTubeSource
from ...utils import gen_id


async def add_source(session: AsyncSession, pipeline_id: str, *, channel_id: str | None = None, channel_title: str | None = None, playlist_id: str | None = None, custom_url: str | None = None, source_type: str = "channel") -> YouTubeSource:
    source = YouTubeSource(
        id=gen_id("yt"),
        pipeline_id=pipeline_id,
        source_type=source_type,
        channel_id=channel_id,
        channel_title=channel_title,
        playlist_id=playlist_id,
        custom_url=custom_url,
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source


async def get_source(session: AsyncSession, source_id: str) -> YouTubeSource | None:
    return await session.get(YouTubeSource, source_id)


async def list_sources(session: AsyncSession, pipeline_id: str) -> Sequence[YouTubeSource]:
    result = await session.execute(select(YouTubeSource).where(YouTubeSource.pipeline_id == pipeline_id).order_by(YouTubeSource.created_at))
    return result.scalars().all()


async def delete_source(session: AsyncSession, source_id: str) -> bool:
    source = await session.get(YouTubeSource, source_id)
    if source is None:
        return False
    await session.delete(source)
    await session.commit()
    return True


async def set_source_error(session: AsyncSession, source_id: str, error: str, status: str = "error") -> YouTubeSource | None:
    from datetime import datetime, timezone
    source = await session.get(YouTubeSource, source_id)
    if source is None:
        return None
    source.status = status
    source.last_scan_error = error
    source.last_scan_at = datetime.now(timezone.utc)
    session.add(source)
    await session.commit()
    return source


async def touch_source_scan(session: AsyncSession, source_id: str) -> None:
    from datetime import datetime, timezone
    source = await session.get(YouTubeSource, source_id)
    if source is not None:
        source.last_scan_at = datetime.now(timezone.utc)
        source.last_scan_error = None
