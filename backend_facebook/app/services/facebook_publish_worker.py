"""Single-shot Facebook -> YouTube publish worker (Task 8B).

new -> queued (atomic claim) -> processing -> AI metadata ensure (cache or
1 ToolNet call) -> resolve once -> download once -> resumable upload with
AI title/description/hashtags -> publication published + reel published.

AI failure releases the reel BEFORE any download. No raw-caption fallback
when AI is enabled. One job per instance. No scheduler, no loops.
No signed URLs or tokens in responses/logs.
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
from ..db.repositories import destinations, pipelines, publications, reels, youtube_auth
from .facebook_ai_metadata import MetadataError, ensure_ai_metadata
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
    validate_visibility,
)

logger = logging.getLogger("backend-facebook.publish-worker")

_PUBLISH_LOCK = asyncio.Lock()


@dataclass
class PublishJobResult:
    result: str  # published | no_work | failed | busy | already_published
    reel_id: str | None = None
    reel_db_id: str | None = None
    publication_id: str | None = None
    youtube_video_id: str | None = None
    channel_id: str | None = None
    file_bytes: int = 0
    elapsed_s: float = 0.0
    error_code: str | None = None
    error: str | None = None
    ai_cached: bool | None = None
    ai_model: str | None = None
    title: str | None = None


def _redact(message: str) -> str:
    text = message or ""
    for secret in (
        settings.FASTSAVER_API_KEY,
        settings.TURSO_AUTH_TOKEN,
        settings.GOOGLE_CLIENT_SECRET,
    ):
        if secret and len(secret) > 4 and secret in text:
            text = text.replace(secret, "***")
    return text[:500]


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


async def run_publish_next(
    pipeline_id: str,
    destination_id: str,
    *,
    tmp_root: Path = TMP_ROOT,
    transport: httpx.AsyncBaseTransport | None = None,
    youtube_factory=None,
) -> PublishJobResult:
    """Publish one claimed reel to one destination. Cleans up in all paths."""
    if _PUBLISH_LOCK.locked():
        return PublishJobResult(
            result="busy", error_code="PUBLISH_BUSY", error="Another publish is running."
        )
    async with _PUBLISH_LOCK:
        return await _run_guarded(
            pipeline_id, destination_id,
            tmp_root=tmp_root, transport=transport, youtube_factory=youtube_factory,
        )


async def _fail(
    publication_id: str | None,
    target_dir: Path,
    started: float,
    error_code: str,
    error: str,
    **extra,
) -> PublishJobResult:
    if publication_id:
        await publications.mark_failed(publication_id, f"{error_code}: {error}")
    reel_db_id = extra.get("reel_db_id")
    if reel_db_id:
        await reels.record_reel_error(reel_db_id, f"{error_code}: {error}")
        await reels.release_claim(reel_db_id)
        await reels.release_processing(reel_db_id)
    cleanup_job_dir(target_dir)
    return PublishJobResult(
        result="failed", elapsed_s=time.monotonic() - started,
        error_code=error_code, error=_redact(error), **extra,
    )


async def _run_guarded(
    pipeline_id: str,
    destination_id: str,
    *,
    tmp_root: Path,
    transport: httpx.AsyncBaseTransport | None,
    youtube_factory,
) -> PublishJobResult:
    started = time.monotonic()
    pipeline = await pipelines.get_pipeline(pipeline_id)
    if pipeline is None:
        return PublishJobResult(result="no_work", error_code="PIPELINE_NOT_FOUND", error="Pipeline not found.")

    destination, dest_error = await _validate_destination(pipeline_id, destination_id)
    if destination is None:
        code = dest_error or "DESTINATION_NOT_FOUND"
        if code == "DESTINATION_NOT_FOUND":
            return PublishJobResult(result="no_work", error_code=code, error="Destination not found.")
        return PublishJobResult(result="failed", error_code=code, error=_redact(code))

    reel, claimed = await reels.claim_next_reel(pipeline_id)
    if not claimed or reel is None:
        return PublishJobResult(result="no_work")

    reel_db_id: str = reel["id"]
    reel_id: str = reel["reel_id"]
    base = {"reel_id": reel_id, "reel_db_id": reel_db_id}
    job_id = f"pub_{uuid.uuid4().hex[:12]}"
    target_dir = job_dir(job_id, tmp_root)
    publication_id = f"pub_{uuid.uuid4().hex[:12]}"

    publication, created = await publications.get_or_create(
        publication_id=publication_id, reel_db_id=reel_db_id, destination_id=destination_id
    )
    if publication["status"] == "published":
        # Never upload twice for the same (reel, destination).
        await reels.release_claim(reel_db_id)
        cleanup_job_dir(target_dir)
        return PublishJobResult(
            result="already_published", publication_id=publication["id"],
            youtube_video_id=publication.get("youtube_video_id"),
            elapsed_s=time.monotonic() - started, **base,
        )
    await publications.mark_processing(publication["id"])
    if not await reels.advance_status(reel_db_id, "queued", "processing"):
        return await _fail(
            publication["id"], target_dir, started,
            "CLAIM_LOST", "Reel left queued state before processing.", **base,
        )

    # AI metadata FIRST: cache hit or exactly one ToolNet call. Any failure
    # releases the reel before a single byte is downloaded. No raw fallback.
    try:
        ensured = await ensure_ai_metadata(reel, transport=transport)
    except MetadataError as exc:
        return await _fail(
            publication["id"], target_dir, started,
            exc.code, str(exc), **base,
        )
    ai_title = (ensured.metadata.title or "").strip()
    if not ai_title or len(ai_title) > 100:
        return await _fail(
            publication["id"], target_dir, started,
            "AI_METADATA_INVALID", "Generated title is empty or over 100 chars.",
            **{**base, "ai_cached": ensured.cached, "ai_model": ensured.model},
        )
    ai_description = finalize_description(ensured.metadata.description, ensured.metadata.hashtags)
    ai_info = {
        "ai_cached": ensured.cached,
        "ai_model": ensured.model,
        "title": ai_title,
    }

    try:
        resolver = FacebookMediaResolver.from_settings(transport=transport)
    except FacebookMediaError as exc:
        return await _fail(
            publication["id"], target_dir, started,
            exc.code, str(exc), **{**base, **ai_info},
        )

    try:
        media = await resolver.resolve(reel.get("reel_url") or "")
        output = await resolver.download_media(media, job_id, tmp_root=tmp_root)
        file_bytes = output.stat().st_size
        if file_bytes <= 0:
            raise FacebookMediaError("MEDIA_DOWNLOAD_FAILED", "Downloaded file is empty.")
    except FacebookMediaError as exc:
        return await _fail(
            publication["id"], target_dir, started,
            exc.code, str(exc), **{**base, **ai_info},
        )
    except Exception as exc:
        return await _fail(
            publication["id"], target_dir, started,
            "UNEXPECTED", type(exc).__name__, **{**base, **ai_info},
        )

    try:
        credentials = await load_destination_credentials_async(destination_id)
        credentials = await refresh_if_needed(destination_id, credentials)
        youtube_video_id = await asyncio.to_thread(
            upload_video, credentials, output, ai_title, ai_description,
            destination.get("visibility") or "public",
            youtube_factory=youtube_factory,
        )
    except YouTubePublisherError as exc:
        return await _fail(
            publication["id"], target_dir, started,
            exc.code, str(exc), **{**base, "file_bytes": file_bytes, **ai_info},
        )
    except Exception as exc:
        return await _fail(
            publication["id"], target_dir, started,
            "UNEXPECTED", type(exc).__name__, **{**base, "file_bytes": file_bytes, **ai_info},
        )

    try:
        await publications.mark_published(
            publication["id"], youtube_video_id,
            title=ai_title, description=ai_description,
            hashtags=ensured.metadata.hashtags, ai_model=ensured.model,
        )
        await reels.mark_reel_published(reel_db_id, youtube_video_id)
    except Exception as exc:
        # Uploaded on YouTube but DB persist failed: keep the video id in the
        # failure note (operator can reconcile) and release the reel for retry.
        # already_published dedupe prevents silent double-uploads once fixed.
        cleanup_job_dir(target_dir)
        await publications.mark_failed(
            publication["id"], f"PERSIST_FAILED vid={youtube_video_id}: {type(exc).__name__}"
        )
        await reels.record_reel_error(reel_db_id, "PERSIST_FAILED")
        await reels.release_processing(reel_db_id)
        await reels.release_claim(reel_db_id)
        return PublishJobResult(
            result="failed", publication_id=publication["id"],
            youtube_video_id=youtube_video_id,
            elapsed_s=time.monotonic() - started,
            error_code="PERSIST_FAILED",
            error=_redact(f"DB persist failed after upload vid={youtube_video_id}"),
            **{**base, "file_bytes": file_bytes},
        )
    cleanup_job_dir(target_dir)
    return PublishJobResult(
        result="published", publication_id=publication["id"],
        youtube_video_id=youtube_video_id, channel_id=destination.get("channel_id"),
        file_bytes=file_bytes, elapsed_s=time.monotonic() - started,
        **{**base, **ai_info},
    )
