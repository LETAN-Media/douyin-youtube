from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import QuotaState


async def get_or_create_quota(session: AsyncSession, pipeline_id: str, date_str: str, quota_limit: int) -> QuotaState:
    row = await session.get(QuotaState, (pipeline_id, date_str))
    if row is None:
        row = QuotaState(
            pipeline_id=pipeline_id,
            date=date_str,
            quota_limit=quota_limit,
            reset_at=datetime.now(timezone.utc),
        )
        session.add(row)
        await session.flush()
    return row


async def can_publish_today(session: AsyncSession, pipeline_id: str, date_str: str, quota_limit: int) -> bool:
    row = await session.get(QuotaState, (pipeline_id, date_str))
    if row is None:
        return True
    return (row.published_count or 0) < (row.quota_limit or quota_limit)


async def increment_quota(session: AsyncSession, pipeline_id: str, date_str: str) -> QuotaState:
    row = await session.get(QuotaState, (pipeline_id, date_str))
    if row is None:
        row = await get_or_create_quota(session, pipeline_id, date_str, 5)
    row.published_count += 1
    row.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(row)
    return row


async def get_quota(session: AsyncSession, pipeline_id: str, date_str: str) -> QuotaState | None:
    return await session.get(QuotaState, (pipeline_id, date_str))
