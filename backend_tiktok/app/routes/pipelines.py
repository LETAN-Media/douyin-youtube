from fastapi import APIRouter, Depends, HTTPException, status

from ..dependencies import require_admin
from ..db.repositories import pipelines as pipelines_repo

router = APIRouter(prefix="/api/tiktok/pipelines", tags=["pipelines"])


@router.get("/", dependencies=[Depends(require_admin)])
async def list_pipelines():
    return await pipelines_repo.list_pipelines()


@router.post("/", dependencies=[Depends(require_admin)])
async def create_pipeline(payload: dict):
    pid = payload.get("id") or payload.get("pipeline_id")
    if not pid:
        raise HTTPException(status_code=400, detail="id required")
    return await pipelines_repo.create_pipeline(
        pipeline_id=pid,
        name=payload.get("name", ""),
        slug=payload.get("slug", pid),
        auto_publish=payload.get("auto_publish", True),
    )


@router.get("/{pipeline_id}", dependencies=[Depends(require_admin)])
async def get_pipeline(pipeline_id: str):
    row = await pipelines_repo.get_pipeline(pipeline_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return row


@router.patch("/{pipeline_id}", dependencies=[Depends(require_admin)])
async def update_pipeline(pipeline_id: str, body: dict):
    """Update pipeline settings: name, enabled, auto_publish, youtube_upload_mode."""
    mode = body.get("youtube_upload_mode")
    if mode is not None:
        try:
            pipelines_repo.normalize_upload_mode(mode)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    row = await pipelines_repo.update_pipeline(
        pipeline_id,
        name=body.get("name"),
        enabled=body.get("enabled"),
        auto_publish=body.get("auto_publish"),
        youtube_upload_mode=mode,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return row


@router.patch("/{pipeline_id}/enable", dependencies=[Depends(require_admin)])
async def toggle_pipeline_enable(pipeline_id: str, body: dict):
    row = await pipelines_repo.update_pipeline_enable(pipeline_id, body.get("enabled", True))
    if row is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return row


@router.patch("/{pipeline_id}/auto_publish", dependencies=[Depends(require_admin)])
async def toggle_auto_publish(pipeline_id: str, body: dict):
    """AUTO ON/OFF per pipeline — separate from enabled."""
    row = await pipelines_repo.update_pipeline_auto_publish(
        pipeline_id, body.get("auto_publish", True)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return row


@router.post("/{pipeline_id}/inventory/exclude", dependencies=[Depends(require_admin)])
async def bulk_exclude_reels(pipeline_id: str, body: dict):
    from ..db.repositories import reels as reels_repo
    reel_ids = body.get("reel_ids", [])
    if not isinstance(reel_ids, list):
        raise HTTPException(status_code=400, detail="reel_ids must be a list")
    return await reels_repo.bulk_exclude_reels(pipeline_id, [str(r) for r in reel_ids])


@router.post("/{pipeline_id}/inventory/restore", dependencies=[Depends(require_admin)])
async def bulk_restore_reels(pipeline_id: str, body: dict):
    from ..db.repositories import reels as reels_repo
    reel_ids = body.get("reel_ids", [])
    if not isinstance(reel_ids, list):
        raise HTTPException(status_code=400, detail="reel_ids must be a list")
    return await reels_repo.bulk_restore_reels(pipeline_id, [str(r) for r in reel_ids])
