"""Global FIFO publish worker: TikTok reel → YouTube upload.

Dequeues jobs from ``tiktok_publish_queue``, resolves media via the
TikTok provider adapter, verifies format & Shorts eligibility with ffprobe,
applies AI metadata, and uploads to YouTube.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from pathlib import Path

from ..config import settings
from ..db.client import execute
from ..db.repositories import pipelines, publications, publish_queue, reels, system_state
from .tiktok_ai_metadata import generate_ai_metadata
from .tiktok_media import ManualMediaError, ManualResolvedMedia, download_media, resolve_manual_media
from .tiktok_provider import ProviderError
from .tiktok_provider_factory import get_scan_provider
from .tiktok_shorts import ShortsCheckError, classify_upload_format, validate_video_file
from .youtube_publisher import YouTubeQuotaExceededError, publish_video_to_youtube

logger = logging.getLogger("backend-tiktok.services.publisher")

MAX_RETRIES = 3


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


async def publisher_loop(stop_event: asyncio.Event) -> None:
    logger.info("TikTok global publisher started")
    poll_interval = max(settings.tiktok_scheduler_poll_seconds, 5)

    while not stop_event.is_set():
        # Heartbeat update
        try:
            await system_state.set_json("worker:publisher", {
                "status": "idle",
                "last_heartbeat": _now_iso(),
                "service": settings.service_name,
            })
        except Exception:
            pass

        worker_id = f"worker_{secrets.token_hex(4)}"
        job = await publish_queue.claim_next_job(worker_id)
        if job is None:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
                break
            except asyncio.TimeoutError:
                continue
            continue

        try:
            await system_state.set_json("worker:publisher", {
                "status": "processing",
                "last_heartbeat": _now_iso(),
                "current_job_id": job["id"],
                "service": settings.service_name,
            })
        except Exception:
            pass

        try:
            await _process_job(job)
            await publish_queue.complete_job(job["id"], status="done")
        except YouTubeQuotaExceededError as exc:
            logger.warning("YouTube quota exceeded for pipeline %s: %s", job.get("pipeline_id"), exc)
            pause_until = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
            try:
                await execute(
                    """
                    INSERT INTO tiktok_quota_pauses (pipeline_id, paused_until, reason, updated_at)
                    VALUES (:pid, :until, :reason, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                    ON CONFLICT(pipeline_id) DO UPDATE SET
                        paused_until = excluded.paused_until,
                        reason = excluded.reason,
                        updated_at = excluded.updated_at
                    """,
                    {"pid": job["pipeline_id"], "until": pause_until, "reason": str(exc)},
                )
            except Exception:
                pass
            await publish_queue.complete_job(job["id"], status="failed", error=str(exc))
            await publications.mark_failed(job["publication_id"], str(exc))
            await reels.advance_status(job["reel_db_id"], "processing", "scheduled")
        except Exception as exc:
            logger.exception("publisher job %s failed: %s", job["id"], exc)
            err_msg = str(exc)
            await publish_queue.complete_job(job["id"], status="failed", error=err_msg)
            await publications.mark_failed(job["publication_id"], err_msg)
            # Release reel so it doesn't get stuck in processing
            await reels.advance_status(job["reel_db_id"], "processing", "failed")

    logger.info("TikTok global publisher stopped")


async def _process_job(job: dict) -> None:
    pub_id = job["publication_id"]
    reel_db_id = job["reel_db_id"]
    destination_id = job["destination_id"]
    pipeline_id = job["pipeline_id"]

    pub = await publications.get_publication(pub_id)
    if pub is None:
        raise RuntimeError(f"publication {pub_id} not found")

    # If already published with a video ID, skip re-uploading
    if pub.get("youtube_video_id") and pub.get("status") == "published":
        logger.info("Publication %s already published as %s; skipping duplicate upload", pub_id, pub["youtube_video_id"])
        await publish_queue.mark_job_stage(job["id"], "done")
        return

    # Claim reel for processing
    if not await reels.advance_status(reel_db_id, "scheduled", "processing"):
        if not await reels.advance_status(reel_db_id, "new", "processing"):
            if not await reels.advance_status(reel_db_id, "failed", "processing"):
                await publications.mark_failed(pub_id, "Reel not in processable state")
                return

    reel = await reels.get_reel(reel_db_id)
    if reel is None:
        raise RuntimeError(f"reel {reel_db_id} not found")

    video_path: Path | None = None
    try:
        # Step 1: Resolve media direct download URL
        # Note: TikTokSourceAPI only scans creator metadata; direct MP4 downloads
        # must be resolved via the PHIMTAT shortcut provider.
        await publish_queue.mark_job_stage(job["id"], "resolving_media")
        resolved_media: ManualResolvedMedia | None = None
        try:
            resolved_media = await resolve_manual_media(reel["reel_url"])
        except Exception as exc:
            logger.warning(
                "resolve_manual_media failed for %s: %s; trying provider fallback",
                reel["reel_url"],
                exc,
            )

        if not resolved_media or not resolved_media.download_url:
            provider = get_scan_provider()
            try:
                media = await provider.resolve_media(reel["reel_url"])
                if media and media.download_url:
                    resolved_media = _to_manual_media(media, reel["reel_url"])
            except Exception as exc:
                logger.warning("provider.resolve_media fallback failed for %s: %s", reel["reel_url"], exc)

        if not resolved_media or not resolved_media.download_url or not resolved_media.download_url.startswith("http"):
            raise RuntimeError(f"Could not resolve direct download URL for TikTok reel {reel_db_id}")

        # Step 2: Download media to temporary file
        await publish_queue.mark_job_stage(job["id"], "downloading_media")
        video_path = await download_media(resolved_media, job_id=reel_db_id)

        # Step 3: Validate downloaded video file integrity
        await publish_queue.mark_job_stage(job["id"], "validating_media")
        validate_video_file(video_path)

        # Step 4: Shorts & Video format verification via ffprobe
        await publish_queue.mark_job_stage(job["id"], "shorts_check")
        pipe = await pipelines.get_pipeline(pipeline_id)
        requested_mode = (
            pub.get("youtube_upload_mode")
            or (pipe.get("youtube_upload_mode") if pipe else None)
            or "shorts"
        )

        target_format, can_proceed, check_note, probe_info = classify_upload_format(requested_mode, video_path)
        await publications.set_shorts_check(
            pub_id,
            probe_info.get("is_vertical") or probe_info.get("is_square"),
            check_note,
        )

        if not can_proceed:
            logger.warning("Job %s ineligible for requested format '%s': %s", job["id"], requested_mode, check_note)
            await publications.mark_failed(pub_id, f"SHORTS_INELIGIBLE: {check_note}")
            await reels.advance_status(reel_db_id, "processing", "skipped")
            await publish_queue.mark_job_stage(job["id"], "failed", error_code="SHORTS_INELIGIBLE", error=check_note)
            raise RuntimeError(f"SHORTS_INELIGIBLE: {check_note}")

        # Update actual upload mode used (e.g. if 'both' chose 'shorts' or 'video')
        await publications.set_upload_mode(pub_id, target_format)

        # Step 5: AI metadata enrichment
        await publish_queue.mark_job_stage(job["id"], "ai_metadata")
        title = pub.get("youtube_title")
        description = pub.get("youtube_description")
        hashtags = pub.get("youtube_hashtags_json") or "[]"

        if not title:
            ai_result = None
            try:
                ai_result = await generate_ai_metadata(
                    pub.get("ai_model"),
                    reel,
                    reel.get("caption") or resolved_media.caption,
                )
            except Exception as exc:
                logger.warning("AI metadata failed for %s: %s", reel_db_id, exc)

            title = (ai_result or {}).get("title") or reel.get("caption") or resolved_media.caption or "TikTok video"
            description = (ai_result or {}).get("description") or ""
            hashtags = (ai_result or {}).get("hashtags_json") or "[]"

            await publications.set_publication_ai_content(
                pub_id,
                title,
                description,
                hashtags,
                ai_model=(ai_result or {}).get("model"),
            )

        # Step 6: YouTube Upload
        await publish_queue.mark_job_stage(job["id"], "uploading_youtube")
        is_shorts = (target_format == "shorts")
        youtube_video_id = await publish_video_to_youtube(
            destination_id,
            video_path,
            title,
            description,
            hashtags,
            thumbnail_url=reel.get("thumbnail_url") or resolved_media.thumbnail_url,
            is_shorts=is_shorts,
        )
        if not youtube_video_id or not str(youtube_video_id).strip():
            raise RuntimeError("YouTube API did not return a valid video ID")

        # Step 7: Finalize statuses
        await publications.mark_published(pub_id, youtube_video_id)
        await reels.mark_reel_published(reel_db_id, youtube_video_id)
        await publish_queue.mark_job_stage(job["id"], "done")
        logger.info("Successfully published reel %s -> YouTube video %s (%s)", reel_db_id, youtube_video_id, target_format)

    finally:
        # Clean up temporary media files
        if video_path is not None:
            try:
                p = Path(video_path)
                if p.exists():
                    p.unlink()
                if p.parent.exists() and not any(p.parent.iterdir()):
                    p.parent.rmdir()
            except OSError:
                pass


def _to_manual_media(media, source_url: str):
    """Adapt TikTokMedia to ManualResolvedMedia for download_media."""
    from .tiktok_media import ManualResolvedMedia

    return ManualResolvedMedia(
        source_url=source_url,
        download_url=media.download_url,
        content_type=media.content_type,
        caption=media.caption,
        thumbnail_url=media.thumbnail_url,
        duration=media.duration,
        provider=getattr(media, "provider", "provider"),
    )
