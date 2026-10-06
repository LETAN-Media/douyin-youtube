"""Drama pipeline routes (Phase 1: CRUD only)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import require_admin
from ..db.repositories import drama as repo
from ._common import _err

router = APIRouter(prefix="/api/drama", tags=["drama-pipelines"])


class PipelineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=200)
    enabled: bool = True
    auto_publish: bool = True


@router.get("/pipelines")
async def list_pipelines(_: None = Depends(require_admin)) -> list[dict]:
    return repo.list_pipelines()


@router.post("/pipelines", status_code=201)
async def create_pipeline(body: PipelineCreate, _: None = Depends(require_admin)) -> dict:
    try:
        return repo.create_pipeline(
            name=body.name, slug=body.slug, enabled=body.enabled,
            auto_publish=body.auto_publish,
        )
    except ValueError as exc:
        raise _err(409, "PIPELINE_EXISTS", str(exc))


@router.get("/pipelines/{pipeline_id}")
async def get_pipeline(pipeline_id: str, _: None = Depends(require_admin)) -> dict:
    pipeline = repo.get_pipeline(pipeline_id)
    if pipeline is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found.")
    return pipeline
