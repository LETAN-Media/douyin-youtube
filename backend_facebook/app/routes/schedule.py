"""Weekly schedule admin APIs (Task 9)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import require_admin
from ..db.repositories import pipelines, publish_queue, schedules
from ..db.repositories.schedules import MAX_DAILY_PUBLISH
from ..services.facebook_global_publisher import get_publisher_status, run_publisher_once
from ..services.facebook_scheduler import describe_schedule_status, run_scheduler_tick
from ..services.schedule_generator import (
    DistributionMode,
    ScheduleGenerationConfig,
    ScheduleGenerationError,
    generate_weekly_schedule,
    preview_generated_schedule,
    slots_to_dict,
)

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
    max_daily_publish: int = Field(default=5, ge=1, le=MAX_DAILY_PUBLISH)
    batch_time: str | None = Field(default=None, max_length=8)
    slots: dict[str, list[str]] | None = None


class ScheduleGenerationRequest(BaseModel):
    max_daily_publish: int = Field(ge=1, le=1000)
    start_time: str = Field(pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")
    end_time: str = Field(pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")
    min_interval_minutes: int = Field(ge=1, le=1440)
    weekdays: list[int] = Field(min_length=1, max_length=7)
    distribution_mode: str = Field(default="even")
    allow_midnight: bool = False
    separate_weekend: bool = False
    weekend_start_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")
    weekend_end_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")
    weekend_min_interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    weekend_max_daily_publish: int | None = Field(default=None, ge=1, le=1000)


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


@router.post("/pipelines/{pipeline_id}/schedule/preview")
async def preview_schedule(
    pipeline_id: str, body: ScheduleGenerationRequest, _: None = Depends(require_admin)
) -> dict:
    """Preview generated schedule without saving."""
    if await pipelines.get_pipeline(pipeline_id) is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found")

    # Get current schedule to use timezone if not specified
    current = await schedules.get_schedule(pipeline_id)
    tz = current.get("timezone") if current else "Asia/Ho_Chi_Minh"

    try:
        # Validate distribution mode
        try:
            dist_mode = DistributionMode(body.distribution_mode)
        except ValueError:
            raise _err(400, "INVALID_DISTRIBUTION_MODE", f"Unknown distribution mode: {body.distribution_mode}")

        config = ScheduleGenerationConfig(
            max_daily_publish=body.max_daily_publish,
            start_time=body.start_time,
            end_time=body.end_time,
            min_interval_minutes=body.min_interval_minutes,
            weekdays=body.weekdays,
            distribution_mode=dist_mode,
            allow_midnight=body.allow_midnight,
            separate_weekend=body.separate_weekend,
            weekend_start_time=body.weekend_start_time,
            weekend_end_time=body.weekend_end_time,
            weekend_min_interval_minutes=body.weekend_min_interval_minutes,
            weekend_max_daily_publish=body.weekend_max_daily_publish,
        )
        result = generate_weekly_schedule(config)
        return {
            "ok": True,
            "slots": slots_to_dict(result.slots),
            "warnings": result.warnings,
            "feasibility_report": result.feasibility_report,
        }
    except ScheduleGenerationError as e:
        return {
            "ok": False,
            "error": e.code,
            "message": e.message,
            "details": e.details,
        }
    except Exception as e:
        raise _err(400, "GENERATION_FAILED", str(e))


@router.post("/pipelines/{pipeline_id}/schedule/generate")
async def generate_and_save_schedule(
    pipeline_id: str, body: ScheduleGenerationRequest, _: None = Depends(require_admin)
) -> dict:
    """Generate schedule and save to database."""
    if await pipelines.get_pipeline(pipeline_id) is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found")

    # Preview first
    preview = await preview_schedule(pipeline_id, body, _)
    if not preview.get("ok"):
        raise _err(400, preview.get("error", "GENERATION_FAILED"), preview.get("message", "Schedule generation failed"))

    # Save the generated schedule
    try:
        schedule = await schedules.upsert_schedule(
            pipeline_id,
            enabled=True,
            timezone=body.timezone if hasattr(body, 'timezone') and body.timezone else "Asia/Ho_Chi_Minh",
            max_daily_publish=body.max_daily_publish,
            slots=preview["slots"],
            batch_time=body.batch_time if hasattr(body, 'batch_time') and body.batch_time else "06:00",
        )
    except ValueError as exc:
        raise _err(400, "INVALID_SCHEDULE", str(exc) or "Invalid schedule.")

    # Get current schedule to use timezone if not specified
    current = await schedules.get_schedule(pipeline_id)
    tz = current.get("timezone") if current else "Asia/Ho_Chi_Minh"

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
        "warnings": preview.get("warnings", []),
        "feasibility_report": preview.get("feasibility_report", {}),
    }


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
    """Manual "run batch now".

    Bypasses the batch_time gate (force_now=True) but keeps future-slot-only
    selection, the daily limit, the AI-ready requirement and durable enqueue.
    Does no download/upload; the global publisher worker handles those.
    """
    from ..services.facebook_scheduler import execute_daily_batch

    pipeline = await pipelines.get_pipeline(pipeline_id)
    if pipeline is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found")
    schedule = await schedules.get_schedule(pipeline_id)
    if schedule is None or not schedule.get("enabled"):
        raise _err(400, "SCHEDULER_NOT_ENABLED", "Scheduler is not enabled for this pipeline.")

    outcome = await execute_daily_batch(
        pipeline_id,
        destination_id,
        force_now=True,
        now=datetime.now(timezone.utc),
    )
    enqueued = outcome["videos_enqueued"]
    reason = outcome["reason"]

    # A reason means nothing new was queued. Never report "executed" in that case.
    if reason:
        return {
            "ok": False,
            "batch_id": outcome["batch_id"],
            "status": outcome["batch_status"] or "no_work",
            "videos_enqueued": enqueued,
            "slots": [],
            "reason": reason,
            "message": outcome["message"] or "Không có video nào được xếp vào hàng đợi.",
            "daily_limit": outcome.get("daily_limit"),
            "slot_capacity": outcome.get("slot_capacity"),
            "capacity_limited": outcome.get("capacity_limited", False),
            "warning": outcome.get("warning"),
        }

    return {
        "ok": True,
        "batch_id": outcome["batch_id"],
        "status": "executed",
        "videos_enqueued": enqueued,
        "slots": outcome["slots"],
        "reason": None,
        "message": (
            outcome.get("warning")
            or f"Đã xếp {enqueued} video vào hàng đợi."
        ),
        "daily_limit": outcome.get("daily_limit"),
        "slot_capacity": outcome.get("slot_capacity"),
        "capacity_limited": outcome.get("capacity_limited", False),
        "warning": outcome.get("warning"),
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
