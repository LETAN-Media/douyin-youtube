from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import require_admin
from ..db.repositories import pipelines as pipelines_repo
from ..db.repositories import destinations as destinations_repo

router = APIRouter(prefix="/api/tiktok/schedule", tags=["schedule"])


@router.get("/pipeline/{pipeline_id}", dependencies=[Depends(require_admin)])
async def get_schedule(pipeline_id: str):
    from ..db.repositories import schedules

    row = await schedules.get_by_pipeline(pipeline_id)
    if row is None:
        row = await schedules.get_or_create_schedule(pipeline_id)
    return row


@router.patch("/pipeline/{pipeline_id}/enabled", dependencies=[Depends(require_admin)])
async def toggle_schedule(pipeline_id: str, body: dict):
    from ..db.repositories import schedules

    schedule = await schedules.set_schedule_enabled(pipeline_id, body.get("enabled", True))
    return schedule


@router.patch("/pipeline/{pipeline_id}/settings", dependencies=[Depends(require_admin)])
async def update_schedule(pipeline_id: str, body: dict):
    from ..db.repositories import schedules

    max_daily = body.get("max_daily")
    if max_daily is not None:
        try:
            val = int(max_daily)
            if val < 1 or val > 10:
                raise HTTPException(
                    status_code=400,
                    detail="Số video đăng trong ngày (max_daily) phải từ 1 đến 10.",
                )
            max_daily = val
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="max_daily không hợp lệ.")

    return await schedules.update_schedule(
        pipeline_id,
        timezone=body.get("timezone"),
        max_daily=max_daily,
        batch_time=body.get("batch_time"),
        active_days=body.get("active_days"),
        weekend_priority=body.get("weekend_priority"),
        video_order=body.get("video_order"),
        min_interval_minutes=body.get("min_interval_minutes"),
    )


@router.post("/pipeline/{pipeline_id}/run-now", dependencies=[Depends(require_admin)])
async def run_schedule_batch_now(pipeline_id: str, body: dict | None = None):
    """Manually trigger daily batch scheduling for this pipeline immediately."""
    from ..services.tiktok_scheduler import execute_daily_batch

    dest_id = (body or {}).get("destination_id")
    result = await execute_daily_batch(pipeline_id, destination_id=dest_id, force_now=True)
    return result


@router.get("/pipeline/{pipeline_id}/slots", dependencies=[Depends(require_admin)])
async def list_slots(pipeline_id: str):
    from ..db.repositories import schedules

    schedule = await schedules.get_by_pipeline(pipeline_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return await schedules.list_slots(schedule["id"])


@router.patch("/pipeline/{pipeline_id}/slots/generate", dependencies=[Depends(require_admin)])
async def generate_slots(pipeline_id: str, body: dict):
    from ..services import schedule_generator

    try:
        max_daily = max(1, min(10, int(body.get("max_daily", 5))))
    except (ValueError, TypeError):
        max_daily = 5
    batch_time = body.get("batch_time", "06:00")
    return await schedule_generator.generate_week_schedule(pipeline_id, max_daily, batch_time)


@router.patch("/slot/{slot_id}", dependencies=[Depends(require_admin)])
async def update_slot(slot_id: str, body: dict):
    from ..db.client import execute

    weekday = body.get("weekday")
    slot_time = body.get("slot_time")
    enabled = body.get("enabled")
    updates = []
    params = {"id": slot_id}
    if weekday is not None:
        updates.append("weekday = :weekday")
        params["weekday"] = weekday
    if slot_time is not None:
        updates.append("slot_time = :slot_time")
        params["slot_time"] = slot_time
    if enabled is not None:
        updates.append("enabled = :enabled")
        params["enabled"] = 1 if enabled else 0
    if updates:
        await execute(
            f"UPDATE tiktok_publish_schedule_slots SET {', '.join(updates)}, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
            params,
        )
    return {"status": "updated", "slot_id": slot_id}
