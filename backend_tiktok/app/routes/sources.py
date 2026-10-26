import uuid
from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import require_admin
from ..db.repositories import sources as sources_repo
from ..services.tiktok_url import resolve_tiktok_input

router = APIRouter(prefix="/api/tiktok/sources", tags=["sources"])


@router.get("/pipeline/{pipeline_id}", dependencies=[Depends(require_admin)])
async def list_sources(pipeline_id: str):
    return await sources_repo.list_sources(pipeline_id)


@router.post("/", dependencies=[Depends(require_admin)])
async def create_source(payload: dict):
    pipeline_id = payload.get("pipeline_id")
    if not pipeline_id:
        raise HTTPException(status_code=400, detail="pipeline_id is required")

    raw_user = (
        payload.get("username")
        or payload.get("source_url")
        or payload.get("url")
        or payload.get("handle")
    )
    if not raw_user:
        raise HTTPException(status_code=400, detail="username or profile url is required")

    try:
        username, canonical_url = await resolve_tiktok_input(raw_user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Check if source already exists in pipeline (idempotent, avoids UNIQUE constraint error)
    existing = await sources_repo.get_source_by_username(pipeline_id, username)
    if existing:
        return existing

    sid = payload.get("id") or payload.get("source_id") or f"src_{uuid.uuid4().hex[:12]}"
    display_name = payload.get("display_name") or f"@{username}"
    source_url = payload.get("source_url") or canonical_url

    return await sources_repo.create_source(
        source_id=sid,
        pipeline_id=pipeline_id,
        username=username,
        display_name=display_name,
        source_url=source_url,
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
