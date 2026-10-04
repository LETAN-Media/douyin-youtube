"""AI metadata endpoints (Task 8A). Admin-only generation, public-safe reads."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_admin
from ..db.repositories import ai_metadata as ai_repo
from ..db.repositories import reels
from ..services.facebook_ai_metadata import MetadataError, ensure_ai_metadata

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
        ensured = await ensure_ai_metadata(reel)
    except MetadataError as exc:
        await ai_repo.mark_failed(reel_db_id, f"{exc.code}: {exc}")
        raise _err(ERROR_STATUS.get(exc.code, 500), exc.code, str(exc))
    return {
        "ok": True,
        "reel_id": reel.get("reel_id"),
        "status": "generated",
        "metadata": {
            "title": ensured.metadata.title,
            "description": ensured.metadata.description,
            "hashtags": ensured.metadata.hashtags,
        },
        "model": ensured.model,
        "cached": ensured.cached,
        "usage": ensured.usage,
    }


@router.get("/reels/{reel_db_id}/ai-metadata")
async def get_metadata(reel_db_id: str, _: None = Depends(require_admin)) -> dict:
    row = await ai_repo.get_for_reel(reel_db_id)
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
    return await ai_repo.pipeline_stats(pipeline_id)
