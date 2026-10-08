"""Single-worker loop: recover stale -> claim -> process -> scheduler ticks.

Concurrency is fixed at 1 render job at a time (PHASE 18). Runs inside the
API process lifespan and shuts down gracefully.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

logger = logging.getLogger("backend-audio.worker")

_worker_task: asyncio.Task | None = None
_stop = asyncio.Event()
WORKER_ID = f"audio-worker-{uuid.uuid4().hex[:6]}"


async def _loop() -> None:
    from pathlib import Path

    from app.config import settings
    from app.db.repositories import jobs as jobs_repo
    from app.db.repositories import pipelines as pipe_repo
    from app.services.processing import run_audio_job
    from app.services.scheduler import tick_pipeline

    workdir = Path(settings.AUDIO_WORKDIR)
    workdir.mkdir(parents=True, exist_ok=True)
    recovered = jobs_repo.recover_stale_running()
    if recovered:
        logger.info("recovered %d stale jobs to queued", recovered)
    while not _stop.is_set():
        try:
            job = jobs_repo.claim_next_queued(WORKER_ID)
            if job:
                logger.info("worker picked job %s", job["id"])
                try:
                    await run_audio_job(job["id"], workdir=workdir,
                                        timeout_s=settings.AUDIO_JOB_TIMEOUT_SECONDS)
                except Exception as exc:
                    logger.exception("job %s crashed: %s", job["id"], exc)
                    jobs_repo.update_job(job["id"], status="failed",
                                         last_error_code="WORKER_CRASH",
                                         last_error_message=str(exc)[:500])
                continue
            for pipe in pipe_repo.list_pipelines():
                if not pipe.get("enabled") or not pipe.get("auto_publish"):
                    continue
                try:
                    tick_pipeline(pipe["id"])
                except Exception as exc:
                    logger.warning("scheduler tick %s: %s", pipe["id"], exc)
        except Exception as exc:
            logger.exception("worker loop error: %s", exc)
        try:
            await asyncio.wait_for(_stop.wait(), timeout=15)
        except asyncio.TimeoutError:
            pass


def start() -> None:
    global _worker_task

    if _worker_task is None or _worker_task.done():
        _stop.clear()
        _worker_task = asyncio.create_task(_loop())
        logger.info("audio worker started (%s)", WORKER_ID)


async def stop() -> None:
    global _worker_task

    _stop.set()
    if _worker_task is not None:
        try:
            await asyncio.wait_for(_worker_task, timeout=30)
        except asyncio.TimeoutError:
            _worker_task.cancel()
        _worker_task = None
    logger.info("audio worker stopped")


def status() -> dict:
    running = _worker_task is not None and not _worker_task.done()
    return {"worker_id": WORKER_ID, "running": running}
