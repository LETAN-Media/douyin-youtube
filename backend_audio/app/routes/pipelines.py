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


class PipelineUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    auto_publish: bool | None = None


@router.get("/pipelines")
async def list_pipelines(_: None = Depends(require_admin)):
    items = []
    for pipe in repo.list_pipelines():
        stats = repo.pipeline_stats(pipe["id"])
        items.append({**pipe, **stats})
    return {"items": items}


@router.post("/pipelines", status_code=201)
async def create_pipeline(body: PipelineCreate, _: None = Depends(require_admin)):
    pipe = repo.create_pipeline(body.name, enabled=body.enabled,
                                auto_publish=body.auto_publish)
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
    pipe = repo.update_pipeline(pipeline_id, **body.model_dump(exclude_none=True))
    return {**pipe, **repo.pipeline_stats(pipeline_id)}


@router.delete("/pipelines/{pipeline_id}")
async def delete_pipeline(pipeline_id: str, _: None = Depends(require_admin)):
    if repo.get_pipeline(pipeline_id) is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    repo.delete_pipeline(pipeline_id)
    return {"deleted": True}
