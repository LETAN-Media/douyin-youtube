"""Manual publish trigger (Task 7B). Admin-only, single job, no loops."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_admin
from ..db.repositories import pipelines, reels, publications, publish_queue, destinations
from ..services.facebook_global_publisher import run_publisher_once

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

    dest = await destinations.get_destination(destination_id)
    if dest is None or dest.get("pipeline_id") != pipeline_id:
        raise _err(404, "DESTINATION_NOT_FOUND", "Destination not found")

    # Claim next reel and enqueue to global queue with high priority
    reel, claimed = await reels.claim_next_reel(pipeline_id)
    if not claimed or reel is None:
        return {"ok": True, "result": "no_work"}

    reel_db_id = reel["id"]
    reel_id = reel["reel_id"]
    publication_id = f"pub_{__import__('uuid').uuid4().hex[:12]}"

    publication, _ = await publications.get_or_create(
        publication_id=publication_id, reel_db_id=reel_db_id, destination_id=destination_id
    )
    if publication["status"] == "published":
        await reels.release_claim(reel_db_id)
        return {
            "ok": True,
            "result": "already_published",
            "reel_id": reel_id,
            "publication_id": publication["id"],
            "youtube_video_id": publication.get("youtube_video_id"),
        }

    await publications.mark_processing(publication["id"])
    if not await reels.advance_status(reel_db_id, "new", "queued"):
        await publications.mark_failed(publication["id"], "CLAIM_LOST")
        await reels.release_claim(reel_db_id)
        return {"ok": False, "result": "failed", "error_code": "CLAIM_LOST", "error": "Reel claim lost"}

    # Enqueue with high priority (manual = 2000)
    await publish_queue.enqueue_publish_job(
        pipeline_id=pipeline_id,
        destination_id=destination_id,
        reel_db_id=reel_db_id,
        publication_id=publication["id"],
        priority=2000,
    )

    return {
        "ok": True,
        "result": "enqueued",
        "reel_id": reel_id,
        "publication_id": publication["id"],
        "message": "Job enqueued to global publish queue. Processing will start shortly.",
    }
