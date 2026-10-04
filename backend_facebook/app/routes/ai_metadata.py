"""AI metadata endpoints (Task 8A). Admin-only generation, public-safe reads."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_admin
from ..db.repositories import ai_metadata, reels
from ..db.repositories.ai_metadata import source_hash
from ..services.facebook_ai_metadata import FacebookMetadataGenerator, MetadataError

router = APIRouter(prefix="/api/facebook", tags=["facebook-ai"])

ERROR_STATUS = {
    "TOOLNET_CONFIG_MISSING": 500,
    "TOOLNET_AUTH_FAILED": 502,
    "TOOLNET_RATE_LIMITED": 429,
    "TOOLNET_TIMEOUT": 504,
    "TOOLNET_UPSTREAM_ERROR": 502,
    "AI_INVALID_RESPONSE": 502,
    "AI_INSUFFICIENT_CONTEXT": 422,
}


def _err(status_code: int, error: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": error, "message": message})


def _metadata_response(row: dict) -> dict:
    return {
        "title": row.get("title"),
        "description": row.get("description"),
        "hashtags": row.get("hashtags", []),
    }


@router.post("/reels/{reel_db_id}/ai-metadata/generate")
async def generate_metadata(reel_db_id: str, _: None = Depends(require_admin)) -> dict:
    reel = await reels.get_reel(reel_db_id)
    if reel is None:
        raise _err(404, "REEL_NOT_FOUND", "Reel not found")

    try:
        generator = FacebookMetadataGenerator.from_settings()
    except MetadataError as exc:
        raise _err(ERROR_STATUS.get(exc.code, 500), exc.code, str(exc))

    model = generator.config.model
    if not await ai_metadata.needs_generation(
        reel_db_id, reel.get("caption"), model, reel.get("reel_id")
    ):
        row = await ai_metadata.get_for_reel(reel_db_id)
        assert row is not None
        return {
            "ok": True,
            "reel_id": reel.get("reel_id"),
            "status": "generated",
            "metadata": _metadata_response(row),
            "model": row.get("model"),
            "cached": True,
        }

    try:
        generated = await generator.generate(
            reel.get("reel_id") or reel_db_id,
            reel.get("caption"),
            reel.get("reel_url"),
        )
    except MetadataError as exc:
        await ai_metadata.mark_failed(reel_db_id, f"{exc.code}: {exc}")
        raise _err(ERROR_STATUS.get(exc.code, 500), exc.code, str(exc))

    row = await ai_metadata.upsert_generated(
        reel_db_id=reel_db_id,
        title=generated.title,
        description=generated.description,
        hashtags=generated.hashtags,
        model=generated.model,
        source_hash=source_hash(reel.get("caption"), reel.get("reel_id")),
    )
    return {
        "ok": True,
        "reel_id": reel.get("reel_id"),
        "status": "generated",
        "metadata": _metadata_response(row),
        "model": generated.model,
        "cached": False,
        "usage": generated.usage,
    }


@router.get("/reels/{reel_db_id}/ai-metadata")
async def get_metadata(reel_db_id: str, _: None = Depends(require_admin)) -> dict:
    row = await ai_metadata.get_for_reel(reel_db_id)
    if row is None:
        raise _err(404, "METADATA_NOT_FOUND", "No AI metadata for this reel.")
    return {
        "reel_db_id": row["reel_db_id"],
        "status": row["status"],
        "metadata": _metadata_response(row),
        "model": row.get("model"),
    }


@router.get("/pipelines/{pipeline_id}/ai-metadata/stats")
async def ai_stats(pipeline_id: str, _: None = Depends(require_admin)) -> dict:
    return await ai_metadata.pipeline_stats(pipeline_id)
