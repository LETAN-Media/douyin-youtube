"""Weekly schedule admin APIs (Task 9)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import require_admin
from ..db.repositories import pipelines, schedules
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
    print(f"DEBUG put_schedule: pipeline={pipeline_id} batch_time={body.batch_time!r}")
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
