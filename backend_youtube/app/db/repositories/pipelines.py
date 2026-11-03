from datetime import datetime
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Pipeline, YouTubeVideo
from ...utils import gen_id


async def create_pipeline(session: AsyncSession, *, name: str, description: str | None = None, **kwargs) -> Pipeline:
    pipeline = Pipeline(id=gen_id("youtube"), name=name, description=description, **kwargs)
    session.add(pipeline)
    await session.commit()
    await session.refresh(pipeline)
    return pipeline


async def get_pipeline(session: AsyncSession, pipeline_id: str) -> Pipeline | None:
    return await session.get(Pipeline, pipeline_id)


async def list_pipelines(session: AsyncSession, limit: int = 100, offset: int = 0) -> Sequence[Pipeline]:
    result = await session.execute(select(Pipeline).order_by(Pipeline.created_at.desc()).limit(limit).offset(offset))
    return result.scalars().all()


async def update_pipeline(session: AsyncSession, pipeline_id: str, **fields) -> Pipeline | None:
    pipeline = await session.get(Pipeline, pipeline_id)
    if pipeline is None:
        return None
    for key, value in fields.items():
        if value is not None:
            setattr(pipeline, key, value)
    session.add(pipeline)
    await session.commit()
    await session.refresh(pipeline)
    return pipeline


async def delete_pipeline(session: AsyncSession, pipeline_id: str) -> bool:
    pipeline = await session.get(Pipeline, pipeline_id)
    if pipeline is None:
        return False
    await session.delete(pipeline)
    await session.commit()
    return True


async def touch_pipeline_next_scan(session: AsyncSession, pipeline_id: str, dt: datetime) -> None:
    pipeline = await session.get(Pipeline, pipeline_id)
    if pipeline is not None:
        pipeline.next_scan_at = dt


async def count_videos(session: AsyncSession, pipeline_id: str) -> int:
    result = await session.execute(select(func.count()).select_from(YouTubeVideo).where(YouTubeVideo.pipeline_id == pipeline_id))
    return result.scalar_one()
