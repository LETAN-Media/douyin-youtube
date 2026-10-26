from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import require_admin
from ..db.repositories import reels as reels_repo

router = APIRouter(prefix="/api/tiktok/inventory", tags=["inventory"])


@router.get("/source/{source_id}", dependencies=[Depends(require_admin)])
async def list_reels(
    source_id: str,
    status: str | None = Query(default=None),
    limit: int = Query(default=100),
):
    if status:
        rows = await reels_repo.list_reels(source_id, status=status)
        return rows[:limit]
    return await reels_repo.list_reels(source_id)


@router.get("/pipeline/{pipeline_id}", dependencies=[Depends(require_admin)])
async def list_pipeline_inventory(
    pipeline_id: str,
    status: str | None = Query(default=None),
    limit: int = Query(default=100),
):
    return await reels_repo.list_reels_for_pipeline(pipeline_id, status=status, limit=limit)


@router.get("/source/{source_id}/unpublished", dependencies=[Depends(require_admin)])
async def list_unpublished(source_id: str, limit: int = 50):
    return await reels_repo.list_unpublished_reels(source_id, limit=limit)


@router.get("/source/{source_id}/stats", dependencies=[Depends(require_admin)])
async def source_stats(source_id: str):
    return {
        "total": await reels_repo.count_reels(source_id),
        "unpublished": await reels_repo.count_unpublished(source_id),
        "published": await reels_repo.count_published(source_id),
        "excluded": await reels_repo.count_excluded(source_id),
    }


@router.get("/reel/{reel_db_id}", dependencies=[Depends(require_admin)])
async def get_reel(reel_db_id: str):
    row = await reels_repo.get_reel(reel_db_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Video không tồn tại trong kho")
    return row


@router.delete("/reels/{reel_db_id}", dependencies=[Depends(require_admin)])
async def delete_reel(
    reel_db_id: str,
    pipeline_id: str | None = Query(default=None),
):
    """Delete (exclude) a video from inventory."""
    from ..services.dashboard_cache import invalidate_pipeline

    res = await reels_repo.exclude_reel(reel_db_id, pipeline_id=pipeline_id)
    if not res.get("ok"):
        code = res.get("error_code")
        if code == "NOT_FOUND":
            raise HTTPException(status_code=404, detail=res["message"])
        elif code == "PIPELINE_MISMATCH":
            raise HTTPException(status_code=403, detail=res["message"])
        elif code == "PROCESSING":
            raise HTTPException(status_code=409, detail=res["message"])
        else:
            raise HTTPException(status_code=400, detail=res["message"])
    pid = res.get("pipeline_id") or pipeline_id
    if pid:
        invalidate_pipeline(pid)
    return res


@router.post("/reels/{reel_db_id}/exclude", dependencies=[Depends(require_admin)])
async def exclude_reel(
    reel_db_id: str,
    body: dict | None = None,
    pipeline_id: str | None = Query(default=None),
):
    """POST alias for deleting/excluding a video from inventory."""
    from ..services.dashboard_cache import invalidate_pipeline

    pid = (body.get("pipeline_id") if body else None) or pipeline_id
    res = await reels_repo.exclude_reel(reel_db_id, pipeline_id=pid)
    if not res.get("ok"):
        code = res.get("error_code")
        if code == "NOT_FOUND":
            raise HTTPException(status_code=404, detail=res["message"])
        elif code == "PIPELINE_MISMATCH":
            raise HTTPException(status_code=403, detail=res["message"])
        elif code == "PROCESSING":
            raise HTTPException(status_code=409, detail=res["message"])
        else:
            raise HTTPException(status_code=400, detail=res["message"])
    target_pid = res.get("pipeline_id") or pid
    if target_pid:
        invalidate_pipeline(target_pid)
    return res


@router.post("/reels/{reel_db_id}/restore", dependencies=[Depends(require_admin)])
async def restore_reel(
    reel_db_id: str,
    body: dict | None = None,
    pipeline_id: str | None = Query(default=None),
):
    """Restore an excluded video back to active inventory."""
    from ..services.dashboard_cache import invalidate_pipeline

    pid = (body.get("pipeline_id") if body else None) or pipeline_id
    res = await reels_repo.restore_reel(reel_db_id, pipeline_id=pid)
    if not res.get("ok"):
        code = res.get("error_code")
        if code == "NOT_FOUND":
            raise HTTPException(status_code=404, detail=res["message"])
        elif code == "PIPELINE_MISMATCH":
            raise HTTPException(status_code=403, detail=res["message"])
        elif code == "NOT_EXCLUDED":
            raise HTTPException(status_code=409, detail=res["message"])
        else:
            raise HTTPException(status_code=400, detail=res["message"])
    target_pid = res.get("pipeline_id") or pid
    if target_pid:
        invalidate_pipeline(target_pid)
    return res


@router.post("/pipelines/{pipeline_id}/exclude", dependencies=[Depends(require_admin)])
async def bulk_exclude_inventory(pipeline_id: str, body: dict):
    from ..services.dashboard_cache import invalidate_pipeline

    reel_ids = body.get("reel_ids", [])
    if not isinstance(reel_ids, list):
        raise HTTPException(status_code=400, detail="reel_ids must be a list")
    res = await reels_repo.bulk_exclude_reels(pipeline_id, [str(r) for r in reel_ids])
    invalidate_pipeline(pipeline_id)
    return res


@router.post("/pipelines/{pipeline_id}/restore", dependencies=[Depends(require_admin)])
async def bulk_restore_inventory(pipeline_id: str, body: dict):
    from ..services.dashboard_cache import invalidate_pipeline

    reel_ids = body.get("reel_ids", [])
    if not isinstance(reel_ids, list):
        raise HTTPException(status_code=400, detail="reel_ids must be a list")
    res = await reels_repo.bulk_restore_reels(pipeline_id, [str(r) for r in reel_ids])
    invalidate_pipeline(pipeline_id)
    return res


@router.patch("/reel/{reel_db_id}/status", dependencies=[Depends(require_admin)])
async def update_reel_status(reel_db_id: str, body: dict):
    await reels_repo.update_reel_status(reel_db_id, body.get("status", "new"))
    return {"status": "updated", "reel_db_id": reel_db_id}
