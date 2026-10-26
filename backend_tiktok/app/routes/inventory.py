from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import require_admin
from ..db.repositories import reels as reels_repo

router = APIRouter(prefix="/api/tiktok/inventory", tags=["inventory"])


@router.get("/source/{source_id}", dependencies=[Depends(require_admin)])
async def list_reels(
    source_id: str,
    status: str | None = Query(default=None),
    limit: int = Query(default=50),
):
    if status:
        rows = await reels_repo.list_reels(source_id)
        rows = [r for r in rows if r.get("status") == status][:limit]
        return rows
    return await reels_repo.list_reels(source_id)


@router.get("/source/{source_id}/unpublished", dependencies=[Depends(require_admin)])
async def list_unpublished(source_id: str, limit: int = 50):
    return await reels_repo.list_unpublished_reels(source_id, limit=limit)


@router.get("/source/{source_id}/stats", dependencies=[Depends(require_admin)])
async def source_stats(source_id: str):
    return {
        "total": await reels_repo.count_reels(source_id),
        "unpublished": await reels_repo.count_unpublished(source_id),
        "published": await reels_repo.count_published(source_id),
    }


@router.get("/reel/{reel_db_id}", dependencies=[Depends(require_admin)])
async def get_reel(reel_db_id: str):
    row = await reels_repo.get_reel(reel_db_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Reel not found")
    return row


@router.patch("/reel/{reel_db_id}/status", dependencies=[Depends(require_admin)])
async def update_reel_status(reel_db_id: str, body: dict):
    await reels_repo.update_reel_status(reel_db_id, body.get("status", "new"))
    return {"status": "updated", "reel_db_id": reel_db_id}
