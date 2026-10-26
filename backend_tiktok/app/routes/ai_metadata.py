from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import require_admin
from ..db.repositories import ai_metadata, ai_settings

router = APIRouter(prefix="/api/tiktok/ai", tags=["ai-metadata"])


@router.get("/settings/pipeline/{pipeline_id}", dependencies=[Depends(require_admin)])
async def get_ai_settings(pipeline_id: str):
    row = await ai_settings.get_ai_settings(pipeline_id)
    if row is None:
        await ai_settings.create_or_update_ai_settings(pipeline_id)
        row = await ai_settings.get_ai_settings(pipeline_id)
    return row


@router.patch("/settings/pipeline/{pipeline_id}", dependencies=[Depends(require_admin)])
async def update_ai_settings(pipeline_id: str, body: dict):
    return await ai_settings.create_or_update_ai_settings(
        pipeline_id,
        enabled=body.get("enabled"),
        system_prompt=body.get("system_prompt"),
        title_template=body.get("title_template"),
        description_template=body.get("description_template"),
        locked_hashtags_json=body.get("locked_hashtags_json"),
        language=body.get("language"),
        model=body.get("model"),
    )


@router.get("/metadata/reel/{reel_db_id}", dependencies=[Depends(require_admin)])
async def get_metadata(reel_db_id: str):
    row = await ai_metadata.get_metadata(reel_db_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Metadata not found")
    return row


@router.post("/metadata/regenerate/{reel_db_id}", dependencies=[Depends(require_admin)])
async def regenerate(reel_db_id: str, background=None):
    from ..services.tiktok_scan import _format_create_time
    from ..db.repositories import reels

    reel = await reels.get_reel(reel_db_id)
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")

    import hashlib

    source_hash = hashlib.sha256((reel.get("caption") or "").encode()).hexdigest()[:32]
    await ai_metadata.create_metadata_entry(reel_db_id, source_hash)
    await ai_metadata.set_pending(reel_db_id, source_hash)
    return {"status": "queued", "reel_db_id": reel_db_id}
