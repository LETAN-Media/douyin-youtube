from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import require_admin
from ..db.repositories import sources as sources_repo

router = APIRouter(prefix="/api/tiktok/sources", tags=["sources"])


@router.get("/pipeline/{pipeline_id}", dependencies=[Depends(require_admin)])
async def list_sources(pipeline_id: str):
    return await sources_repo.list_sources(pipeline_id)


@router.post("/", dependencies=[Depends(require_admin)])
async def create_source(payload: dict):
    sid = payload.get("id") or payload.get("source_id")
    username = payload.get("username")
    if not sid or not username:
        raise HTTPException(status_code=400, detail="id and username required")
    return await sources_repo.create_source(
        source_id=sid,
        pipeline_id=payload["pipeline_id"],
        username=username,
        display_name=payload.get("display_name"),
        source_url=payload.get("source_url"),
    )


@router.get("/{source_id}", dependencies=[Depends(require_admin)])
async def get_source(source_id: str):
    row = await sources_repo.get_source(source_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return row


@router.patch("/{source_id}/enable", dependencies=[Depends(require_admin)])
async def toggle_source(source_id: str, body: dict):
    enabled = body.get("enabled", True)
    await sources_repo.update_scan_state(source_id, scan_status=None)
    from ..db.client import execute
    await execute(
        "UPDATE tiktok_sources SET enabled = :enabled, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = :id",
        {"id": source_id, "enabled": 1 if enabled else 0},
    )
    return {"status": "updated", "source_id": source_id, "enabled": enabled}
