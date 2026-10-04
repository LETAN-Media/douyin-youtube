"""Single-shot Facebook download worker (Task 6C).

Inventory reel -> atomic claim -> FastSaver resolve (once) -> stream
download (once) -> verify -> cleanup -> back to new (no publish yet).

No infinite loops, no parallel downloads per instance (asyncio guard),
no signed URLs or API keys in responses/logs.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..config import settings
from ..db.repositories import pipelines, reels
from .facebook_media import (
    TMP_ROOT,
    FacebookMediaError,
    FacebookMediaResolver,
    ResolvedFacebookMedia,
    cleanup_job_dir,
    job_dir,
)

logger = logging.getLogger("backend-facebook.download-worker")

# One download job at a time per instance (0.2 vCPU / 512 MB).
_JOB_LOCK = asyncio.Lock()


@dataclass
class DownloadJobResult:
    result: str  # downloaded | no_work | failed | busy
    reel_id: str | None = None
    reel_db_id: str | None = None
    file_bytes: int = 0
    elapsed_s: float = 0.0
    error_code: str | None = None
    error: str | None = None


def _redact(message: str) -> str:
    text = message or ""
    for secret in (settings.FASTSAVER_API_KEY, settings.TURSO_AUTH_TOKEN):
        if secret and len(secret) > 4 and secret in text:
            text = text.replace(secret, "***")
    return text[:500]


async def run_download_next(
    pipeline_id: str,
    *,
    tmp_root: Path = TMP_ROOT,
    transport: httpx.AsyncBaseTransport | None = None,
) -> DownloadJobResult:
    """Claim one reel and test-download it. Never leaves temp files or stale queued."""
    if _JOB_LOCK.locked():
        return DownloadJobResult(result="busy", error_code="DOWNLOAD_BUSY", error="Another download is running.")
    async with _JOB_LOCK:
        return await _run_guarded(pipeline_id, tmp_root=tmp_root, transport=transport)


async def _run_guarded(
    pipeline_id: str,
    *,
    tmp_root: Path,
    transport: httpx.AsyncBaseTransport | None,
) -> DownloadJobResult:
    started = time.monotonic()
    pipeline = await pipelines.get_pipeline(pipeline_id)
    if pipeline is None:
        return DownloadJobResult(result="no_work", error_code="PIPELINE_NOT_FOUND", error="Pipeline not found.")

    reel, claimed = await reels.claim_next_reel(pipeline_id)
    if not claimed or reel is None:
        return DownloadJobResult(result="no_work")

    reel_db_id: str = reel["id"]
    reel_id: str = reel["reel_id"]
    job_id = f"dl_{uuid.uuid4().hex[:12]}"
    target_dir = job_dir(job_id, tmp_root)

    try:
        resolver = FacebookMediaResolver.from_settings(transport=transport)
    except FacebookMediaError as exc:
        await reels.record_reel_error(reel_db_id, f"{exc.code}: {exc}")
        await reels.release_claim(reel_db_id)
        return DownloadJobResult(
            result="failed", reel_id=reel_id, reel_db_id=reel_db_id,
            elapsed_s=time.monotonic() - started,
            error_code=exc.code, error=_redact(str(exc)),
        )

    try:
        media: ResolvedFacebookMedia = await resolver.resolve(reel.get("reel_url") or "")
        output = await resolver.download_media(media, job_id, tmp_root=tmp_root)
        file_bytes = output.stat().st_size
        if file_bytes <= 0:
            raise FacebookMediaError("MEDIA_DOWNLOAD_FAILED", "Downloaded file is empty.")
    except FacebookMediaError as exc:
        await reels.record_reel_error(reel_db_id, f"{exc.code}: {exc}")
        await reels.release_claim(reel_db_id)
        cleanup_job_dir(target_dir)
        return DownloadJobResult(
            result="failed", reel_id=reel_id, reel_db_id=reel_db_id,
            elapsed_s=time.monotonic() - started,
            error_code=exc.code, error=_redact(str(exc)),
        )
    except Exception as exc:  # never leave queued stale
        await reels.record_reel_error(reel_db_id, f"UNEXPECTED: {type(exc).__name__}")
        await reels.release_claim(reel_db_id)
        cleanup_job_dir(target_dir)
        return DownloadJobResult(
            result="failed", reel_id=reel_id, reel_db_id=reel_db_id,
            elapsed_s=time.monotonic() - started,
            error_code="UNEXPECTED", error=_redact(f"{type(exc).__name__}"),
        )

    # Test-download verified: hand the reel back for the future publish step.
    # (No YouTube yet, so NEVER mark published here.)
    cleanup_job_dir(target_dir)
    released = await reels.release_claim(reel_db_id)
    if not released:
        logger.warning("job %s could not release claim on %s", job_id, reel_db_id)
    return DownloadJobResult(
        result="downloaded", reel_id=reel_id, reel_db_id=reel_db_id,
        file_bytes=file_bytes, elapsed_s=time.monotonic() - started,
    )
