from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import BackgroundJob, JobStatus
from ...utils import gen_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_job(
    session: AsyncSession,
    pipeline_id: str,
    job_type: str,
    payload: dict | None = None,
    *,
    scheduled_for: datetime | None = None,
    priority: int = 0,
    max_attempts: int = 5,
) -> BackgroundJob:
    job = BackgroundJob(
        id=gen_id("job"),
        pipeline_id=pipeline_id,
        job_type=job_type,
        payload=payload or {},
        scheduled_for=scheduled_for or _now(),
        priority=priority,
        max_attempts=max_attempts,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def claim_jobs(
    session: AsyncSession,
    pipeline_id: str,
    worker_id: str,
    job_type: str | None,
    concurrency: int = 1,
    stale_ttl: int = 300,
    now: datetime | None = None,
) -> Sequence[BackgroundJob]:
    if now is None:
        now = _now()
    expired = now - timedelta(seconds=stale_ttl)
    clause = and_(
        BackgroundJob.pipeline_id == pipeline_id,
        BackgroundJob.status == JobStatus.PENDING,
        BackgroundJob.scheduled_for <= now,
        (
            BackgroundJob.reservation_expires_at.is_(None)
            | (BackgroundJob.reservation_expires_at < expired)
        ),
    )
    if job_type is not None:
        clause = and_(clause, BackgroundJob.job_type == job_type)
    stmt = (
        select(BackgroundJob)
        .where(clause)
        .order_by(BackgroundJob.priority.desc(), BackgroundJob.scheduled_for)
        .limit(concurrency)
    )
    from ...db.session import is_postgres
    if is_postgres():
        stmt = stmt.with_for_update(skip_locked=True)
    result = await session.execute(stmt)
    rows = result.scalars().unique().all()
    token = gen_id("jobworker")
    for row in rows:
        row.status = JobStatus.PROCESSING
        row.reservation_token = token
        row.reservation_expires_at = now + timedelta(seconds=stale_ttl)
        row.attempt += 1
    await session.commit()
    for row in rows:
        await session.refresh(row)
    return rows


async def update_job_status(session: AsyncSession, job_id: str, status: str, *, result: dict | None = None, error: str | None = None, error_code: str | None = None) -> BackgroundJob | None:
    job = await session.get(BackgroundJob, job_id)
    if job is None:
        return None
    job.status = status
    if result is not None:
        job.result = result
    if error is not None:
        job.last_error = error
    if error_code is not None:
        job.error_code = error_code
    if status in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED):
        job.reservation_token = None
        job.reservation_expires_at = None
    await session.commit()
    await session.refresh(job)
    return job


async def release_job_reservation(session: AsyncSession, job_id: str) -> BackgroundJob | None:
    job = await session.get(BackgroundJob, job_id)
    if job is None:
        return None
    job.reservation_token = None
    job.reservation_expires_at = None
    if job.status == JobStatus.PROCESSING:
        job.status = JobStatus.PENDING
    await session.commit()
    await session.refresh(job)
    return job


async def requeue_failed_job(session: AsyncSession, job_id: str, scheduled_for: datetime | None = None) -> BackgroundJob | None:
    job = await session.get(BackgroundJob, job_id)
    if job is None:
        return None
    job.status = JobStatus.PENDING
    job.reservation_token = None
    job.reservation_expires_at = None
    job.scheduled_for = scheduled_for or _now()
    job.retry_count += 1
    await session.commit()
    await session.refresh(job)
    return job


async def list_jobs(session: AsyncSession, pipeline_id: str, limit: int = 50) -> Sequence[BackgroundJob]:
    result = await session.execute(
        select(BackgroundJob).where(BackgroundJob.pipeline_id == pipeline_id).order_by(BackgroundJob.created_at.desc()).limit(limit)
    )
    return result.scalars().all()
