from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import require_admin
from ..db.repositories import ai_metadata, ai_settings

router = APIRouter(prefix="/api/tiktok/ai", tags=["ai-metadata"])


@router.get("/models", dependencies=[Depends(require_admin)])
async def list_ai_models():
    return {
        "models": [
            {"id": "groq/openai/gpt-oss-120b", "label": "Groq / GPT-OSS 120B (Nhanh & Tối ưu SEO)", "provider": "toolnet", "is_default": True},
            {"id": "openrouter/openai/gpt-4o-mini", "label": "GPT-4o Mini (Thông minh & Ổn định)", "provider": "toolnet", "is_default": False},
            {"id": "openrouter/openai/gpt-4o", "label": "GPT-4o (Chất lượng cao nhất)", "provider": "toolnet", "is_default": False},
            {"id": "openrouter/anthropic/claude-3.5-sonnet", "label": "Claude 3.5 Sonnet (Văn phong mượt mà)", "provider": "toolnet", "is_default": False},
        ]
    }


@router.get("/settings/pipeline/{pipeline_id}", dependencies=[Depends(require_admin)])
async def get_ai_settings(pipeline_id: str):
    return await ai_settings.get_ai_settings(pipeline_id)


@router.put("/settings/pipeline/{pipeline_id}", dependencies=[Depends(require_admin)])
@router.patch("/settings/pipeline/{pipeline_id}", dependencies=[Depends(require_admin)])
async def update_ai_settings(pipeline_id: str, body: dict):
    return await ai_settings.create_or_update_ai_settings(
        pipeline_id,
        enabled=body.get("enabled"),
        provider=body.get("provider"),
        model=body.get("model"),
        system_prompt=body.get("system_prompt"),
        title_prompt=body.get("title_prompt"),
        description_prompt=body.get("description_prompt"),
        hashtag_prompt=body.get("hashtag_prompt"),
        title_template=body.get("title_template"),
        description_template=body.get("description_template"),
        locked_hashtags=body.get("locked_hashtags"),
        locked_hashtags_json=body.get("locked_hashtags_json"),
        language=body.get("language"),
        max_hashtags=body.get("max_hashtags"),
        include_emojis=body.get("include_emojis"),
        tone=body.get("tone"),
        required_keywords=body.get("required_keywords"),
        forbidden_keywords=body.get("forbidden_keywords"),
    )


@router.post("/test", dependencies=[Depends(require_admin)])
async def run_ai_test(body: dict):
    """Test AI metadata generation without saving or publishing."""
    pipeline_id = body.get("pipeline_id")
    sample_caption = body.get("sample_caption") or body.get("caption") or body.get("sample_title") or "Khám phá video TikTok triệu view"
    settings_override = body.get("settings")

    from ..services.tiktok_ai_metadata import generate_ai_metadata

    try:
        res = await generate_ai_metadata(
            pipeline_id=pipeline_id,
            original_caption=sample_caption,
            override_settings=settings_override,
        )
        return res
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Lỗi AI: {exc}")


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
