"""Global publisher worker (Task 12).

Single global worker that processes the publish queue sequentially.
Ensures only ONE heavy job (AI metadata -> FastSaver -> download -> YouTube upload)
runs at a time across ALL pipelines.

Fair scheduling via round-robin across pipelines.
Durable queue in Turso survives restarts.
Multi-instance safe via atomic DB claim.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path

import httpx

from ..config import settings
from ..db.repositories import ai_metadata as ai_metadata_repo, destinations, pipelines, publications, publish_queue, reels, youtube_auth
from .facebook_media import (
    TMP_ROOT,
    FacebookMediaError,
    FacebookMediaResolver,
    cleanup_job_dir,
    job_dir,
)
from .facebook_youtube_publisher import (
    YouTubePublisherError,
    finalize_description,
    load_destination_credentials_async,
    refresh_if_needed,
    upload_video,
    validate_publish_at,
    validate_visibility,
)

logger = logging.getLogger("backend-facebook.global-publisher")

WORKER_ID = f"worker_{uuid.uuid4().hex[:8]}"


async def _validate_destination(pipeline_id: str, destination_id: str) -> tuple[dict | None, str | None]:
    """Returns (destination, error_code). No claim/download happens before this."""
    destination = await destinations.get_destination(destination_id)
    if destination is None or destination.get("pipeline_id") != pipeline_id:
        return None, "DESTINATION_NOT_FOUND"
    if not destination.get("enabled", True):
        return None, "DESTINATION_DISABLED"
    if not destination.get("connected"):
        return None, "DESTINATION_NOT_CONNECTED"
    if not destination.get("channel_id"):
        return None, "DESTINATION_NOT_CONNECTED"
    if not await youtube_auth.get_credentials(destination_id):
        return None, "DESTINATION_NOT_CONNECTED"
    try:
        validate_visibility(destination.get("visibility"))
    except YouTubePublisherError:
        return None, "INVALID_VISIBILITY"
    return destination, None


async def _fail_job(
    queue_id: str,
    publication_id: str | None,
    target_dir: Path,
    started: float,
    error_code: str,
    error: str,
    **extra,
) -> dict:
    if publication_id:
        await publications.mark_failed(publication_id, f"{error_code}: {error}")
    reel_db_id = extra.get("reel_db_id")
    if reel_db_id:
        await reels.record_reel_error(reel_db_id, f"{error_code}: {error}")
        await reels.release_claim(reel_db_id)
        await reels.release_processing(reel_db_id)
    cleanup_job_dir(target_dir)
    await publish_queue.update_job_status(
        queue_id, "failed", stage="failed", error_code=error_code, error=error
    )
    return {
        "queue_id": queue_id,
        "result": "failed",
        "elapsed_s": time.monotonic() - started,
        "error_code": error_code,
        "error": error,
        **extra,
    }


async def _process_one_job(
    queue_job: dict,
    transport: httpx.AsyncBaseTransport | None = None,
    youtube_factory=None,
) -> dict:
    """Process a single publish queue job. Returns result dict."""
    queue_id = queue_job["id"]
    pipeline_id = queue_job["pipeline_id"]
    destination_id = queue_job["destination_id"]
    reel_db_id = queue_job["reel_db_id"]
    publication_id = queue_job["publication_id"]
    started = time.monotonic()

    await publish_queue.update_job_status(queue_id, "processing", stage="validating")

    pipeline = await pipelines.get_pipeline(pipeline_id)
    if pipeline is None:
        return await _fail_job(
            queue_id, publication_id, Path("/tmp"), started,
            "PIPELINE_NOT_FOUND", "Pipeline not found.",
            reel_db_id=reel_db_id,
        )

    destination, dest_error = await _validate_destination(pipeline_id, destination_id)
    if destination is None:
        code = dest_error or "DESTINATION_NOT_FOUND"
        return await _fail_job(
            queue_id, publication_id, Path("/tmp"), started,
            code, code,
            reel_db_id=reel_db_id,
        )

    reel = await reels.get_reel(reel_db_id)
    if reel is None:
        return await _fail_job(
            queue_id, publication_id, Path("/tmp"), started,
            "REEL_NOT_FOUND", "Reel not found.",
            reel_db_id=reel_db_id,
        )

    reel_id = reel["reel_id"]
    job_id = f"pub_{uuid.uuid4().hex[:12]}"
    target_dir = job_dir(job_id, TMP_ROOT)
    base = {"reel_id": reel_id, "reel_db_id": reel_db_id, "queue_id": queue_id}

    await publish_queue.update_job_status(queue_id, "processing", stage="claiming")

    if not await reels.advance_status(reel_db_id, "queued", "processing"):
        await reels.release_claim(reel_db_id)
        await reels.release_processing(reel_db_id)
        return await _fail_job(
            queue_id, publication_id, target_dir, started,
            "CLAIM_LOST", "Reel left queued state before processing.",
            **base,
        )

    # Load cached AI metadata (must be pre-generated by AI worker)
    await publish_queue.update_job_status(queue_id, "processing", stage="ai_metadata")
    cached_meta = await ai_metadata_repo.get_metadata(reel_db_id)
    if cached_meta is None or cached_meta.get("status") != "generated":
        return await _fail_job(
            queue_id, publication_id, target_dir, started,
            "AI_METADATA_NOT_READY", "AI metadata not generated. Run AI worker first.",
            **base,
        )

    # Verify config_hash matches current pipeline AI settings
    from ..db.repositories import ai_settings as ai_settings_repo
    pipe_ai_settings = await ai_settings_repo.get_settings(pipeline_id)
    model = settings.TOOLNET_MODEL or ""
    current_config_hash = ai_settings_repo.compute_config_hash(
        enabled=pipe_ai_settings.get("enabled", True),
        system_prompt=pipe_ai_settings.get("system_prompt"),
        title_template=pipe_ai_settings.get("title_template"),
        description_template=pipe_ai_settings.get("description_template"),
        locked_hashtags=pipe_ai_settings.get("locked_hashtags"),
        language=pipe_ai_settings.get("language"),
        model=model,
    )
    if cached_meta.get("config_hash") != current_config_hash:
        return await _fail_job(
            queue_id, publication_id, target_dir, started,
            "AI_METADATA_STALE", "Cached AI metadata config mismatch. Regenerate required.",
            **base,
        )

    ai_title = (cached_meta.get("title") or "").strip()
    if not ai_title or len(ai_title) > 100:
        return await _fail_job(
            queue_id, publication_id, target_dir, started,
            "AI_METADATA_INVALID", "Cached title is empty or over 100 chars.",
            **{**base, "ai_cached": True, "ai_model": cached_meta.get("model")},
        )
    ai_description = finalize_description(
        cached_meta.get("description") or "",
        cached_meta.get("hashtags") or [],
    )
    ai_info = {
        "ai_cached": True,
        "ai_model": cached_meta.get("model"),
        "title": ai_title,
    }

    # Load scheduled_publish_at from publication
    pub = await publications.get_publication(publication_id)
    scheduled_publish_at = pub.get("scheduled_publish_at") if pub else None
    visibility = destination.get("visibility") or "private"
    validated_publish_at = None
    if scheduled_publish_at:
        validated_publish_at = validate_publish_at(scheduled_publish_at)

    # SLOT_MISSED check: if scheduled_publish_at is in the past, don't download/upload
    if validated_publish_at:
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if validated_publish_at <= now_utc:
            return await _fail_job(
                queue_id, publication_id, target_dir, started,
                "SLOT_MISSED", f"Scheduled publishAt {validated_publish_at} has passed. Slot missed.",
                **base,
            )

    try:
        await publish_queue.update_job_status(queue_id, "processing", stage="media_resolve")
        resolver = FacebookMediaResolver.from_settings(transport=transport)
    except FacebookMediaError as exc:
        return await _fail_job(
            queue_id, publication_id, target_dir, started,
            exc.code, str(exc), **{**base, **ai_info},
        )

    try:
        await publish_queue.update_job_status(queue_id, "processing", stage="downloading")
        media = await resolver.resolve(reel.get("reel_url") or "")
        output = await resolver.download_media(media, job_id, tmp_root=TMP_ROOT)
        file_bytes = output.stat().st_size
        if file_bytes <= 0:
            raise FacebookMediaError("MEDIA_DOWNLOAD_FAILED", "Downloaded file is empty.")
    except FacebookMediaError as exc:
        return await _fail_job(
            queue_id, publication_id, target_dir, started,
            exc.code, str(exc), **{**base, **ai_info},
        )
    except Exception as exc:
        return await _fail_job(
            queue_id, publication_id, target_dir, started,
            "UNEXPECTED", type(exc).__name__, **{**base, **ai_info},
        )

    try:
        await publish_queue.update_job_status(queue_id, "processing", stage="uploading")
        credentials = await load_destination_credentials_async(destination_id)
        credentials = await refresh_if_needed(destination_id, credentials)

        pub = await publications.get_publication(publication_id)
        scheduled_publish_at = pub.get("scheduled_publish_at") if pub else None
        visibility = destination.get("visibility") or "private"
        validated_publish_at = None
        if scheduled_publish_at:
            validated_publish_at = validate_publish_at(scheduled_publish_at)

        youtube_video_id = await asyncio.to_thread(
            upload_video, credentials, output, ai_title, ai_description,
            visibility, publish_at=validated_publish_at,
            youtube_factory=youtube_factory,
        )
    except YouTubePublisherError as exc:
        return await _fail_job(
            queue_id, publication_id, target_dir, started,
            exc.code, str(exc), **{**base, "file_bytes": file_bytes, **ai_info},
        )
    except Exception as exc:
        return await _fail_job(
            queue_id, publication_id, target_dir, started,
            "UNEXPECTED", type(exc).__name__, **{**base, "file_bytes": file_bytes, **ai_info},
        )

    try:
        # Determine if we should mark as scheduled (future publishAt) or published (immediate)
        is_scheduled = validated_publish_at is not None
        
        if is_scheduled:
            await publications.mark_scheduled(
                publication_id, youtube_video_id,
                scheduled_publish_at=validated_publish_at,
                title=ai_title, description=ai_description,
                hashtags=cached_meta.get("hashtags") or [],
                ai_model=cached_meta.get("model"),
            )
            await reels.mark_reel_scheduled(reel_db_id, youtube_video_id)
            await publish_queue.update_job_status(queue_id, "scheduled", stage="completed")
        else:
            await publications.mark_published(
                publication_id, youtube_video_id,
                title=ai_title, description=ai_description,
                hashtags=cached_meta.get("hashtags") or [],
                ai_model=cached_meta.get("model"),
            )
            await reels.mark_reel_published(reel_db_id, youtube_video_id)
            await publish_queue.update_job_status(queue_id, "published", stage="completed")
    except Exception as exc:
        cleanup_job_dir(target_dir)
        await publications.mark_failed(
            publication_id, f"PERSIST_FAILED vid={youtube_video_id}: {type(exc).__name__}"
        )
        await reels.record_reel_error(reel_db_id, "PERSIST_FAILED")
        await reels.release_processing(reel_db_id)
        await reels.release_claim(reel_db_id)
        await publish_queue.update_job_status(
            queue_id, "failed", stage="persist_failed",
            error_code="PERSIST_FAILED", error=f"DB persist failed after upload vid={youtube_video_id}"
        )
        return {
            "queue_id": queue_id,
            "result": "failed",
            "publication_id": publication_id,
            "youtube_video_id": youtube_video_id,
            "elapsed_s": time.monotonic() - started,
            "error_code": "PERSIST_FAILED",
            "error": f"DB persist failed after upload vid={youtube_video_id}",
            **{**base, "file_bytes": file_bytes},
        }

    cleanup_job_dir(target_dir)
    is_scheduled = validated_publish_at is not None
    if is_scheduled:
        logger.info(
            "scheduled reel %s video %s via queue %s for publishAt %s",
            reel_id, youtube_video_id, queue_id, validated_publish_at,
        )
        return {
            "queue_id": queue_id,
            "result": "scheduled",
            "publication_id": publication_id,
            "youtube_video_id": youtube_video_id,
            "channel_id": destination.get("channel_id"),
            "scheduled_publish_at": validated_publish_at,
            "file_bytes": file_bytes,
            "elapsed_s": time.monotonic() - started,
            **{**base, **ai_info},
        }
    else:
        logger.info(
            "published reel %s video %s via queue %s immediately",
            reel_id, youtube_video_id, queue_id,
        )
        return {
            "queue_id": queue_id,
            "result": "published",
            "publication_id": publication_id,
            "youtube_video_id": youtube_video_id,
            "channel_id": destination.get("channel_id"),
            "file_bytes": file_bytes,
            "elapsed_s": time.monotonic() - started,
            **{**base, **ai_info},
        }


async def _publisher_loop(
    concurrency: int = 1,
    poll_seconds: int = 5,
    stale_ttl_seconds: int = 300,
    transport: httpx.AsyncBaseTransport | None = None,
    youtube_factory=None,
) -> None:
    """Main publisher loop. Runs forever."""
    logger.info("global publisher started (concurrency=%d, poll=%ds, worker=%s)", concurrency, poll_seconds, WORKER_ID)

    semaphore = asyncio.Semaphore(concurrency)

    async def worker_task() -> None:
        while True:
            async with semaphore:
                # Recover stale jobs first
                recovered = await publish_queue.recover_stale_jobs(stale_ttl_seconds)
                if recovered:
                    logger.info("recovered %d stale processing jobs", recovered)

                # Claim next job (fair scheduling)
                job = await publish_queue.claim_next_job(worker_id=WORKER_ID, max_ttl_seconds=stale_ttl_seconds)
                if job is None:
                    break  # No queued jobs, exit inner loop to sleep

                try:
                    await _process_one_job(job, transport=transport, youtube_factory=youtube_factory)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("unexpected error processing queue job %s: %s", job["id"], exc)
                    await publish_queue.update_job_status(
                        job["id"], "failed", stage="error",
                        error_code="UNEXPECTED", error=str(exc)
                    )

            # Small delay between jobs to avoid tight loop
            await asyncio.sleep(0.1)

    while True:
        try:
            await worker_task()
        except asyncio.CancelledError:
            logger.info("global publisher cancelled")
            raise
        except Exception as exc:
            logger.exception("publisher loop error: %s", exc)

        await asyncio.sleep(max(1, poll_seconds))


async def run_publisher_once(
    transport: httpx.AsyncBaseTransport | None = None,
    youtube_factory=None,
) -> dict | None:
    """Run one iteration of the publisher (for testing/manual trigger)."""
    recovered = await publish_queue.recover_stale_jobs(settings.FACEBOOK_PUBLISH_STALE_TTL_SECONDS)
    if recovered:
        logger.info("recovered %d stale jobs", recovered)

    job = await publish_queue.claim_next_job(worker_id=WORKER_ID, max_ttl_seconds=settings.FACEBOOK_PUBLISH_STALE_TTL_SECONDS)
    if job is None:
        return {"status": "no_work"}

    try:
        result = await _process_one_job(job, transport=transport, youtube_factory=youtube_factory)
        return result
    except Exception as exc:
        logger.exception("run_publisher_once error: %s", exc)
        return {"status": "error", "error": str(exc)}


async def get_publisher_status() -> dict:
    """Get publisher status for dashboard."""
    global_stats = await publish_queue.get_queue_stats()
    current_job = await publish_queue.get_current_job()

    return {
        "worker_id": WORKER_ID,
        "concurrency": settings.FACEBOOK_PUBLISH_CONCURRENCY,
        "enabled": settings.FACEBOOK_PUBLISH_WORKER_ENABLED,
        "global_queue": global_stats,
        "current_job": current_job,
    }