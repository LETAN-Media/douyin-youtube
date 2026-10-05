"""Weekly schedule admin APIs (Task 9)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import require_admin
from ..db.repositories import pipelines, publish_queue, schedules
from ..services.facebook_global_publisher import get_publisher_status, run_publisher_once
from ..services.facebook_scheduler import describe_schedule_status, run_scheduler_tick

router = APIRouter(prefix="/api/facebook", tags=["facebook-schedule"])


def _err(status_code: int, error: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": error, "message": message})


def _present(schedule: dict) -> dict:
    names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    return {
        "id": schedule["id"],
        "pipeline_id": schedule["pipeline_id"],
        "timezone": schedule["timezone"],
        "enabled": schedule["enabled"],
        "max_daily_publish": schedule["max_daily_publish"],
        "batch_time": schedule.get("batch_time") or "06:00",
        "slots": {names[day]: schedule["slots"].get(day, []) for day in range(7)},
        "created_at": schedule.get("created_at"),
        "updated_at": schedule.get("updated_at"),
    }


class ScheduleUpsert(BaseModel):
    enabled: bool = False
    timezone: str | None = Field(default=None, max_length=64)
    max_daily_publish: int = Field(default=5, ge=1, le=5)
    batch_time: str | None = Field(default=None, max_length=8)
    slots: dict[str, list[str]] | None = None


@router.get("/pipelines/{pipeline_id}/schedule")
async def get_schedule(pipeline_id: str, _: None = Depends(require_admin)) -> dict:
    if await pipelines.get_pipeline(pipeline_id) is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found")
    schedule = await schedules.get_schedule(pipeline_id)
    if schedule is None:
        raise _err(404, "SCHEDULE_NOT_FOUND", "No schedule for this pipeline yet.")
    return _present(schedule)


@router.put("/pipelines/{pipeline_id}/schedule")
async def put_schedule(
    pipeline_id: str, body: ScheduleUpsert, _: None = Depends(require_admin)
) -> dict:
    if await pipelines.get_pipeline(pipeline_id) is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found")
    try:
        schedule = await schedules.upsert_schedule(
            pipeline_id,
            enabled=body.enabled,
            timezone=body.timezone,
            max_daily_publish=body.max_daily_publish,
            slots=body.slots,
            batch_time=body.batch_time,
        )
    except ValueError as exc:
        raise _err(400, "INVALID_SCHEDULE", str(exc) or "Invalid schedule.")
    return _present(schedule)


@router.get("/pipelines/{pipeline_id}/schedule/status")
async def get_schedule_status(pipeline_id: str) -> dict:
    status = await describe_schedule_status(pipeline_id)
    if status is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found")
    return status


@router.post("/scheduler/tick")
async def manual_tick(_: None = Depends(require_admin)) -> dict:
    return await run_scheduler_tick()


@router.post("/scheduler/reconcile")
async def manual_reconcile(_: None = Depends(require_admin)) -> dict:
    from ..services.youtube_schedule_reconciler import reconcile_due_scheduled_publications
    result = await reconcile_due_scheduled_publications()
    return result


@router.post("/pipelines/{pipeline_id}/youtube-destinations/{destination_id}/schedule-today")
async def schedule_today(
    pipeline_id: str,
    destination_id: str,
    _: None = Depends(require_admin),
) -> dict:
    from ..db.repositories import pipelines

    pipeline = await pipelines.get_pipeline(pipeline_id)
    if pipeline is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found")
    schedule = await schedules.get_schedule(pipeline_id)
    if schedule is None or not schedule.get("enabled"):
        raise _err(400, "SCHEDULER_NOT_ENABLED", "Scheduler is not enabled for this pipeline.")
    utc_now = datetime.now(timezone.utc)
    tz = ZoneInfo(schedule.get("timezone") or "Asia/Ho_Chi_Minh")
    now_local = utc_now.astimezone(tz)
    date_iso = now_local.date().isoformat()
    batch_time = schedule.get("batch_time") or "06:00"
    existing = await schedules.get_batch(pipeline_id, destination_id, date_iso)
    if existing is not None:
        return {
            "ok": True,
            "batch_id": existing["id"],
            "status": existing["status"],
            "scheduled_today": existing["uploaded_count"],
            "message": "Batch already exists for today.",
        }
    batch_id = f"batch_{uuid.uuid4().hex[:12]}"
    await schedules.create_batch(
        batch_id=batch_id,
        pipeline_id=pipeline_id,
        destination_id=destination_id,
        local_date=date_iso,
        scheduled_batch_time=batch_time,
    )
    return {
        "ok": True,
        "batch_id": batch_id,
        "status": "queued",
        "message": "Batch claimed. Run scheduler tick to execute.",
    }


# Global publisher queue endpoints
@router.get("/publish-queue/status")
async def get_publish_queue_status(_: None = Depends(require_admin)) -> dict:
    return await get_publisher_status()


@router.get("/publish-queue/jobs")
async def list_publish_queue_jobs(
    limit: int = 50, offset: int = 0, _: None = Depends(require_admin)
) -> dict:
    jobs = await publish_queue.list_queued_jobs(limit=limit, offset=offset)
    return {"jobs": jobs, "limit": limit, "offset": offset}


@router.get("/publish-queue/stats")
async def get_publish_queue_stats(pipeline_id: str | None = None, _: None = Depends(require_admin)) -> dict:
    if pipeline_id:
        return await publish_queue.get_pipeline_queue_stats(pipeline_id)
    return await publish_queue.get_queue_stats()


@router.post("/publish-queue/process-next")
async def process_next_publish_job(_: None = Depends(require_admin)) -> dict:
    return await run_publisher_once()


@router.post("/publish-queue/recover")
async def recover_stale_publish_jobs(_: None = Depends(require_admin)) -> dict:
    recovered = await publish_queue.recover_stale_jobs()
    return {"ok": True, "recovered": recovered}
