from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import require_admin
from app.db.repositories import audio as repo
from app.db.repositories import pipelines as pipe_repo

router = APIRouter(prefix="/api/audio", tags=["audio-scheduler"])


def _err(status: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": error, "message": message})


class SchedulerUpdate(BaseModel):
    enabled: bool | None = None
    destination_id: str | None = None
    max_videos_per_day: int | None = Field(default=None, ge=1, le=20)
    min_gap_minutes: int | None = Field(default=None, ge=15)
    timezone: str | None = None
    daily_times: list[str] | None = None
    order_mode: str | None = None
    rotate_sources: bool | None = None


@router.get("/pipelines/{pipeline_id}/scheduler")
async def get_scheduler(pipeline_id: str, _: None = Depends(require_admin)):
    if pipe_repo.get_pipeline(pipeline_id) is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    from app.services.scheduler import pipeline_due

    settings = repo.get_scheduler_settings(pipeline_id)
    due, reason = pipeline_due(pipeline_id)
    return {**settings, "due": due, "due_reason": reason}


@router.put("/pipelines/{pipeline_id}/scheduler")
async def update_scheduler(pipeline_id: str, body: SchedulerUpdate,
                           _: None = Depends(require_admin)):
    pipe = pipe_repo.get_pipeline(pipeline_id)
    if pipe is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    data = body.model_dump(exclude_none=True)
    if pipe.get("pipeline_type") == "manual" and data.get("enabled"):
        return _err(400, "MANUAL_PIPELINE", "Không thể bật scheduler cho pipeline thủ công.")
    if "destination_id" in data and data["destination_id"]:
        dest = repo.get_destination(data["destination_id"])
        if dest is None or dest.get("pipeline_id") != pipeline_id:
            return _err(400, "BAD_DESTINATION",
                        "Destination không thuộc pipeline này.")
    return repo.upsert_scheduler_settings(pipeline_id, **data)


@router.post("/pipelines/{pipeline_id}/scheduler/tick")
async def tick_now(pipeline_id: str, _: None = Depends(require_admin)):
    pipe = pipe_repo.get_pipeline(pipeline_id)
    if pipe is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    if pipe.get("pipeline_type") == "manual":
        return _err(400, "MANUAL_PIPELINE", "Pipeline thủ công không hỗ trợ scheduler.")
    from app.services.scheduler import tick_pipeline

    return tick_pipeline(pipeline_id)
