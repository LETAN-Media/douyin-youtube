"""Drama source routes: attach a source, trigger a scan (no downloads)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import require_admin
from ..db.repositories import drama as repo
from ..services.rapidix import RapidixError
from ..services.scanner import scan_source
from ._common import _err

router = APIRouter(prefix="/api/drama", tags=["drama-sources"])


class SourceCreate(BaseModel):
    provider: str = Field(default="rapidix", max_length=50)
    source_url: str | None = None
    external_series_id: str | None = None
    name: str | None = Field(default=None, max_length=200)
    enabled: bool = True


@router.get("/pipelines/{pipeline_id}/sources")
async def list_sources(pipeline_id: str, _: None = Depends(require_admin)) -> list[dict]:
    if repo.get_pipeline(pipeline_id) is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found.")
    return repo.list_sources(pipeline_id)


@router.post("/pipelines/{pipeline_id}/sources", status_code=201)
async def create_source(
    pipeline_id: str, body: SourceCreate, _: None = Depends(require_admin)
) -> dict:
    try:
        return repo.create_source(
            pipeline_id=pipeline_id,
            provider=(body.provider or "rapidix").strip() or "rapidix",
            source_url=(body.source_url or "").strip() or None,
            external_series_id=(body.external_series_id or "").strip() or None,
            name=(body.name or "").strip() or None,
            enabled=body.enabled,
        )
    except ValueError as exc:
        raise _err(404, "PIPELINE_NOT_FOUND", str(exc))


@router.post("/sources/{source_id}/scan")
async def scan_one_source(
    source_id: str, _: None = Depends(require_admin)
) -> dict:
    try:
        return await scan_source(source_id)
    except ValueError as exc:
        raise _err(404, "SOURCE_NOT_FOUND", str(exc))
    except RapidixError as exc:
        raise _err(502, exc.code or "PROVIDER_ERROR", str(exc) or "Provider failed.")
