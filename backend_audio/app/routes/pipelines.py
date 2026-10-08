from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import require_admin
from app.db.repositories import pipelines as repo

router = APIRouter(prefix="/api/audio", tags=["audio-pipelines"])


def _err(status: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": error, "message": message})


class PipelineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    auto_publish: bool = True
    pipeline_type: str = Field(default="auto", pattern="^(auto|manual)$")


class PipelineUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    auto_publish: bool | None = None
    pipeline_type: str | None = Field(default=None, pattern="^(auto|manual)$")


@router.get("/pipelines")
async def list_pipelines(type: str | None = None,
                         pipeline_type: str | None = None,
                         _: None = Depends(require_admin)):
    filter_type = type or pipeline_type
    items = []
    for pipe in repo.list_pipelines(pipeline_type=filter_type):
        stats = repo.pipeline_stats(pipe["id"])
        items.append({**pipe, **stats})
    return {"items": items}


@router.post("/pipelines", status_code=201)
async def create_pipeline(body: PipelineCreate, _: None = Depends(require_admin)):
    pipe_type = body.pipeline_type
    auto_pub = False if pipe_type == "manual" else body.auto_publish
    pipe = repo.create_pipeline(body.name, enabled=body.enabled,
                                auto_publish=auto_pub,
                                pipeline_type=pipe_type)
    return {**pipe, **repo.pipeline_stats(pipe["id"])}


@router.get("/pipelines/{pipeline_id}")
async def get_pipeline(pipeline_id: str, _: None = Depends(require_admin)):
    pipe = repo.get_pipeline(pipeline_id)
    if pipe is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    return {**pipe, **repo.pipeline_stats(pipeline_id)}


@router.put("/pipelines/{pipeline_id}")
async def update_pipeline(pipeline_id: str, body: PipelineUpdate,
                          _: None = Depends(require_admin)):
    if repo.get_pipeline(pipeline_id) is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    data = body.model_dump(exclude_none=True)
    if data.get("pipeline_type") == "manual" and "auto_publish" not in data:
        data["auto_publish"] = False
    pipe = repo.update_pipeline(pipeline_id, **data)
    return {**pipe, **repo.pipeline_stats(pipeline_id)}


@router.delete("/pipelines/{pipeline_id}")
async def delete_pipeline(pipeline_id: str, _: None = Depends(require_admin)):
    if repo.get_pipeline(pipeline_id) is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    repo.delete_pipeline(pipeline_id)
    return {"deleted": True}
