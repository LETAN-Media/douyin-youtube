"""AI metadata background worker (Task 13).

Generates AI metadata for new reels BEFORE scheduler picks them up.

Flow:
- Scans inventory for reels with status='new' that lack valid AI metadata
- Claims one reel at a time (fair scheduling across pipelines)
- Calls ensure_ai_metadata() which caches result in facebook_ai_metadata
- Releases AI claim; reel stays 'new' for scheduler
- Only ONE heavy AI call per reel (ToolNet rate-limited)

Concurrency:
- FACEBOOK_AI_WORKER_CONCURRENCY=1 (default)
- Respects ToolNet rate limiter (30 req/min, 8000 tokens/min)
- No download/upload/YouTube - metadata only
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

from ..config import settings
from ..db.repositories import ai_metadata, ai_settings, pipelines, publish_queue, reels
from .facebook_ai_metadata import MetadataError, ensure_ai_metadata
from .facebook_media import TMP_ROOT, cleanup_job_dir, job_dir

logger = logging.getLogger("backend-facebook.ai-worker")

WORKER_ID = f"ai-worker_{uuid.uuid4().hex[:8]}"


async def _worker_loop(
    concurrency: int = 1,
    poll_seconds: int = 10,
    stale_ttl_seconds: int = 300,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """Main AI worker loop. Runs forever."""
    logger.info("AI metadata worker started (concurrency=%d, poll=%ds, worker=%s)", concurrency, poll_seconds, WORKER_ID)

    semaphore = asyncio.Semaphore(concurrency)

    async def worker_task() -> None:
        while True:
            async with semaphore:
                # Recover stale AI jobs first
                recovered = await _recover_stale_ai_jobs(stale_ttl_seconds)
                if recovered:
                    logger.info("AI worker recovered %d stale processing jobs", recovered)

                # Claim next reel needing AI metadata
                job = await _claim_next_ai_job(worker_id=WORKER_ID, max_ttl_seconds=stale_ttl_seconds)
                if job is None:
                    break  # No work, exit inner loop to sleep

                try:
                    await _process_ai_job(job, transport=transport)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("unexpected error processing AI job %s: %s", job["reel_db_id"], exc)
                    await _mark_ai_job_failed(job["reel_db_id"], "UNEXPECTED", str(exc))

            # Small delay between jobs
            await asyncio.sleep(0.1)

    while True:
        try:
            await worker_task()
        except asyncio.CancelledError:
            logger.info("AI metadata worker cancelled")
            raise
        except Exception as exc:
            logger.exception("AI worker loop error: %s", exc)

        await asyncio.sleep(max(1, poll_seconds))


async def _claim_next_ai_job(
    *,
    worker_id: str,
    max_ttl_seconds: int = 300,
) -> dict | None:
    """
    Atomically claim the next reel needing AI metadata.

    Fair scheduling: round-robin across pipelines.
    Returns job dict or None if no work.
    """
    from ..db.repositories import reels as reels_repo
    from ..db.repositories import ai_metadata as ai_metadata_repo
    from ..db.repositories import ai_settings as ai_settings_repo

    # Get all enabled pipelines with AI configured
    all_pipes = await pipelines.list_pipelines()
    enabled_pipes = [p for p in all_pipes if p.get("enabled", True)]

    for pipe in enabled_pipes:
        pipe_id = pipe["id"]

        # Check if AI is enabled for this pipeline
        pipe_ai_settings = await ai_settings_repo.get_settings(pipe_id)
        if not pipe_ai_settings.get("enabled", True):
            continue

        # Check if global AI is enabled
        if not settings.TOOLNET_AI_ENABLED:
            continue

        # Find a reel needing AI metadata
        reel = await _find_reel_needing_ai(pipe_id)
        if reel is None:
            continue

        reel_db_id = reel["id"]

        # Try to claim AI processing
        claimed = await reels_repo.claim_ai_processing(reel_db_id)
        if not claimed:
            continue  # Another worker got it, try next pipeline

        logger.info("AI worker claimed reel %s for pipeline %s", reel["reel_id"], pipe_id)
        return {
            "reel_db_id": reel_db_id,
            "reel_id": reel["reel_id"],
            "pipeline_id": pipe_id,
            "reel": reel,
        }

    return None


async def _find_reel_needing_ai(pipeline_id: str) -> dict | None:
    """Find a reel in 'new' status that needs AI metadata generation."""
    from ..db.repositories import reels as reels_repo
    from ..db.repositories import ai_metadata as ai_metadata_repo
    from ..db.repositories import ai_settings as ai_settings_repo

    # Get pipeline AI settings for config_hash
    pipe_ai_settings = await ai_settings_repo.get_settings(pipeline_id)
    model = settings.TOOLNET_MODEL or ""

    config_hash = pipe_ai_settings.get("config_hash") or ai_settings_repo.compute_config_hash(
        enabled=pipe_ai_settings.get("enabled", True),
        system_prompt=pipe_ai_settings.get("system_prompt"),
        title_template=pipe_ai_settings.get("title_template"),
        description_template=pipe_ai_settings.get("description_template"),
        locked_hashtags=pipe_ai_settings.get("locked_hashtags"),
        language=pipe_ai_settings.get("language"),
        model=model,
    )

    # Find reels needing AI
    reels_needing_ai = await reels_repo.list_reels_needing_ai(pipeline_id, config_hash)
    if not reels_needing_ai:
        return None

    return reels_needing_ai[0]  # Return first one


async def _process_ai_job(job: dict, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Process a single AI metadata job."""
    reel_db_id = job["reel_db_id"]
    reel_id = job["reel_id"]
    pipeline_id = job["pipeline_id"]
    reel = job["reel"]

    logger.info("Generating AI metadata for reel %s (pipeline %s)", reel_id, pipeline_id)

    try:
        # This will generate and cache AI metadata
        ensured = await ensure_ai_metadata(reel, pipeline_id=pipeline_id, transport=transport)

        # Release AI claim, keep reel as 'new' for scheduler
        from ..db.repositories import reels as reels_repo
        await reels_repo.release_ai_claim(reel_db_id)

        logger.info(
            "AI metadata generated for reel %s: title='%s...' cached=%s",
            reel_id, ensured.metadata.title[:30] if ensured.metadata.title else "", ensured.cached
        )
        return {"reel_db_id": reel_db_id, "status": "generated", "title": ensured.metadata.title}

    except MetadataError as exc:
        logger.warning("AI metadata failed for reel %s: %s", reel_id, exc)
        await _mark_ai_job_failed(reel_db_id, exc.code, str(exc))
        return {"reel_db_id": reel_db_id, "status": "failed", "error_code": exc.code}

    except Exception as exc:
        logger.exception("Unexpected error generating AI for reel %s: %s", reel_id, exc)
        await _mark_ai_job_failed(reel_db_id, "UNEXPECTED", str(exc))
        return {"reel_db_id": reel_db_id, "status": "failed", "error_code": "UNEXPECTED"}


async def _mark_ai_job_failed(reel_db_id: str, error_code: str, error: str) -> None:
    """Mark AI job as failed and release claim."""
    from ..db.repositories import reels as reels_repo
    from ..db.repositories import ai_metadata as ai_metadata_repo

    await reels_repo.release_ai_claim(reel_db_id)
    await ai_metadata_repo.mark_failed(reel_db_id, f"{error_code}: {error}")


async def _recover_stale_ai_jobs(ttl_seconds: int = 300) -> int:
    """Recover stuck AI processing jobs that have exceeded TTL."""
    from ..db.repositories import reels as reels_repo

    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=ttl_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = await reels_repo.execute(
        """
        UPDATE facebook_reels
        SET status = 'new', ai_claimed_at = NULL
        WHERE status = 'ai_processing' AND ai_claimed_at < :cutoff
        """,
        {"cutoff": cutoff},
    )
    return rows.rows_affected if hasattr(rows, "rows_affected") else 0


async def run_ai_worker_once(transport: httpx.AsyncBaseTransport | None = None) -> dict | None:
    """Run one iteration of AI worker (for testing/manual trigger)."""
    recovered = await _recover_stale_ai_jobs(settings.FACEBOOK_AI_WORKER_STALE_TTL_SECONDS)
    if recovered:
        logger.info("AI worker recovered %d stale jobs", recovered)

    job = await _claim_next_ai_job(worker_id=WORKER_ID, max_ttl_seconds=settings.FACEBOOK_AI_WORKER_STALE_TTL_SECONDS)
    if job is None:
        return {"status": "no_work"}

    try:
        result = await _process_ai_job(job, transport=transport)
        return result
    except Exception as exc:
        logger.exception("run_ai_worker_once error: %s", exc)
        return {"status": "error", "error": str(exc)}


async def get_ai_worker_status() -> dict:
    """Get AI worker status for dashboard."""
    from ..db.repositories import reels as reels_repo
    from ..db.repositories import ai_metadata as ai_metadata_repo

    # Get counts of reels by AI status
    global_stats = await ai_metadata_repo.get_global_stats()

    return {
        "worker_id": WORKER_ID,
        "concurrency": settings.FACEBOOK_AI_WORKER_CONCURRENCY,
        "enabled": settings.FACEBOOK_AI_WORKER_ENABLED,
        "global_queue": global_stats,
    }