"""Inventory queue endpoints (Task 5).

Read-only inventory + atomic claim for future publish workers.
No downloads, no YouTube, no scheduler.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth import require_admin
from ..db.repositories import pipelines, reels, sources
from ..services.facebook_download_worker import run_download_next

router = APIRouter(prefix="/api/facebook", tags=["facebook-inventory"])


def _err(status_code: int, error: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": error, "message": message})


async def _require_pipeline(pipeline_id: str) -> dict:
    pipeline = await pipelines.get_pipeline(pipeline_id)
    if pipeline is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found")
    return pipeline


@router.get("/pipelines/{pipeline_id}/inventory")
async def get_inventory(
    pipeline_id: str,
    status: str | None = Query(default=None),
    source_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    await _require_pipeline(pipeline_id)
    if source_id:
        source = await sources.get_source(source_id)
        if source is None or source.get("pipeline_id") != pipeline_id:
            raise _err(404, "SOURCE_NOT_FOUND", "Source not found in this pipeline")
    items, total = await reels.list_inventory(
        pipeline_id, status=status, source_id=source_id, limit=limit, offset=offset
    )
    stats = await reels.inventory_stats(pipeline_id)
    next_offset = offset + limit
    return {
        "items": items,
        "total": total,
        "unpublished": stats["unpublished"],
        "published": stats["published"],
        "next_cursor": str(next_offset) if next_offset < total else None,
    }


@router.get("/pipelines/{pipeline_id}/inventory/stats")
async def get_inventory_stats(pipeline_id: str) -> dict:
    await _require_pipeline(pipeline_id)
    return await reels.inventory_stats(pipeline_id)


@router.post("/pipelines/{pipeline_id}/inventory/claim-next")
async def claim_next(pipeline_id: str, _: None = Depends(require_admin)) -> dict:
    await _require_pipeline(pipeline_id)
    reel, claimed = await reels.claim_next_reel(pipeline_id)
    if not claimed or reel is None:
        return {"reel": None, "claimed": False, "reason": "INVENTORY_EMPTY"}
    return {"reel": reel, "claimed": True}
@router.post("/reels/{reel_id}/release")
async def release_reel(reel_id: str, _: None = Depends(require_admin)) -> dict:
    target = reel_id
    if await _get_by_db_id(reel_id) is None:
        matches = await _find_by_reel_id(reel_id)
        if len(matches) != 1:
            raise _err(404, "REEL_NOT_FOUND", "Reel not found")
        target = matches[0]["id"]
    released = await reels.release_claim(target)
    if not released:
        raise _err(409, "RELEASE_REJECTED", "Only queued reels can be released to new")
    return {"id": target, "released": True, "status": "new"}


@router.post("/pipelines/{pipeline_id}/download-next")
async def download_next(pipeline_id: str, _: None = Depends(require_admin)) -> dict:
    """Internal test endpoint: claim 1 reel, resolve + stream-download it, clean up.

    Never returns signed URLs or API keys. No YouTube, no loops.
    """
    await _require_pipeline(pipeline_id)
    job = await run_download_next(pipeline_id)
    if job.result == "busy":
        raise _err(409, "DOWNLOAD_BUSY", "Another download job is already running.")
    if job.result == "no_work":
        if job.error_code == "PIPELINE_NOT_FOUND":
            raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found")
        return {"ok": True, "result": "no_work"}
    if job.result == "failed":
        return {
            "ok": False,
            "result": "failed",
            "reel_id": job.reel_id,
            "error_code": job.error_code,
            "error": job.error,
        }
    return {
        "ok": True,
        "result": "downloaded",
        "reel_id": job.reel_id,
        "bytes": job.file_bytes,
        "elapsed_s": round(job.elapsed_s, 1),
    }


async def _get_by_db_id(reel_db_id: str) -> dict | None:
    return await reels.get_reel(reel_db_id)


async def _find_by_reel_id(reel_id: str) -> list[dict]:
    from ..db.client import get_client

    client = get_client()
    rows = await client.execute(
        "SELECT id FROM facebook_reels WHERE reel_id = :reel_id",
        {"reel_id": reel_id},
    )
    return [{"id": r[0]} for r in (rows.rows or [])]
