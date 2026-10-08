from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth import require_admin
from app.db.repositories import pipelines as pipe_repo
from app.db.repositories import sources as repo

router = APIRouter(prefix="/api/audio", tags=["audio-inventory"])


def _err(status: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": error, "message": message})


class InventoryAdd(BaseModel):
    canonical_url: str
    facebook_video_id: str | None = None
    source_id: str | None = None
    caption: str | None = None
    thumbnail_url: str | None = None
    duration_seconds: float | None = None


@router.get("/pipelines/{pipeline_id}/inventory")
async def list_inventory(pipeline_id: str, status: str | None = None,
                         limit: int = 100, offset: int = 0,
                         _: None = Depends(require_admin)):
    if pipe_repo.get_pipeline(pipeline_id) is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    items, total = repo.list_inventory(pipeline_id, status=status,
                                       limit=min(limit, 500), offset=offset)
    return {"items": items, "total": total}


@router.post("/pipelines/{pipeline_id}/inventory", status_code=201)
async def add_inventory(pipeline_id: str, body: InventoryAdd,
                        _: None = Depends(require_admin)):
    if pipe_repo.get_pipeline(pipeline_id) is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    from app.services import facebook_urls

    try:
        canonical = facebook_urls.canonicalize_facebook_url(body.canonical_url)
    except facebook_urls.FacebookUrlError as exc:
        return _err(400, "INVALID_URL", str(exc))
    item, created = repo.upsert_inventory_item(
        pipeline_id, body.source_id,
        body.facebook_video_id or facebook_urls.extract_facebook_video_id(canonical),
        canonical, caption=body.caption, thumbnail_url=body.thumbnail_url,
        duration_seconds=body.duration_seconds)
    return {"item": item, "created": created}
