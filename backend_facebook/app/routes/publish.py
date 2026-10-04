"""Manual publish trigger (Task 7B). Admin-only, single job, no loops."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_admin
from ..db.repositories import pipelines
from ..services.facebook_publish_worker import run_publish_next

router = APIRouter(prefix="/api/facebook", tags=["facebook-publish"])


def _err(status_code: int, error: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": error, "message": message})


@router.post("/pipelines/{pipeline_id}/youtube-destinations/{destination_id}/publish-next")
async def publish_next(
    pipeline_id: str, destination_id: str, _: None = Depends(require_admin)
) -> dict:
    pipeline = await pipelines.get_pipeline(pipeline_id)
    if pipeline is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found")
    job = await run_publish_next(pipeline_id, destination_id)
    if job.result == "busy":
        raise _err(409, "PUBLISH_BUSY", "Another publish job is already running.")
    if job.result == "no_work":
        if job.error_code in ("PIPELINE_NOT_FOUND", "DESTINATION_NOT_FOUND"):
            raise _err(404, job.error_code, "Not found")
        return {"ok": True, "result": "no_work"}
    if job.result == "already_published":
        return {
            "ok": True,
            "result": "already_published",
            "reel_id": job.reel_id,
            "publication_id": job.publication_id,
            "youtube_video_id": job.youtube_video_id,
        }
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
        "result": "published",
        "reel_id": job.reel_id,
        "publication_id": job.publication_id,
        "youtube_video_id": job.youtube_video_id,
        "channel_id": job.channel_id,
        "bytes": job.file_bytes,
        "elapsed_s": round(job.elapsed_s, 1),
    }
