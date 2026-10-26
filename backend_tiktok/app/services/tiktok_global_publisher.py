"""Global FIFO publish worker: TikTok reel → YouTube upload.

Dequeues jobs from ``tiktok_publish_queue``, resolves media via the
TikTok provider adapter, optionally applies AI metadata, and uploads
to YouTube.
"""

import asyncio
import logging
import secrets
import time

from ..config import settings
from ..db.repositories import publications, publish_queue, reels
from .tiktok_ai_metadata import generate_ai_metadata
from .tiktok_media import ManualMediaError, download_media, resolve_manual_media
from .tiktok_provider import ProviderError
from .tiktok_provider_factory import get_scan_provider
from .youtube_publisher import publish_video_to_youtube

logger = logging.getLogger("backend-tiktok.services.publisher")

MAX_RETRIES = 3


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


async def publisher_loop(stop_event: asyncio.Event) -> None:
    logger.info("TikTok global publisher started")
    poll_interval = max(settings.tiktok_scheduler_poll_seconds, 5)

    while not stop_event.is_set():
        job = await publish_queue.claim_next_job(secrets.token_hex(8))
        if job is None:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
                break
            except asyncio.TimeoutError:
                continue
            continue

        try:
            await _process_job(job)
            await publish_queue.complete_job(job["id"], status="done")
        except Exception as exc:
            logger.exception("publisher job %s failed: %s", job["id"], exc)
            await publish_queue.complete_job(
                job["id"], status="failed", error=str(exc)
            )

    logger.info("TikTok global publisher stopped")


async def _process_job(job: dict) -> None:
    pub_id = job["publication_id"]
    reel_db_id = job["reel_db_id"]
    destination_id = job["destination_id"]

    pub = await publications.get_publication(pub_id)
    if pub is None:
        raise RuntimeError(f"publication {pub_id} not found")

    # Claim the reel for processing
    if not await reels.advance_status(reel_db_id, "scheduled", "processing"):
        # reel may already be in another state; try from 'new'
        if not await reels.advance_status(reel_db_id, "new", "processing"):
            await publications.mark_failed(pub_id, "Reel not in processable state")
            return

    await publish_queue.mark_job_stage(job["id"], "resolving_media")

    # Resolve media via the provider adapter (not a concrete provider)
    reel = await reels.get_reel(reel_db_id)
    if reel is None:
        raise RuntimeError(f"reel {reel_db_id} not found")

    provider = get_scan_provider()
    media = await provider.resolve_media(reel["reel_url"])
    video_path = await download_media(
        _to_manual_media(media, reel["reel_url"]),
        job_id=reel_db_id,
    )

    await publish_queue.mark_job_stage(job["id"], "ai_metadata")

    # AI metadata enrichment
    ai_enabled = True
    ai_result = None
    if ai_enabled:
        try:
            ai_result = await generate_ai_metadata(
                pub.get("ai_model"), reel, reel.get("caption")
            )
        except Exception as exc:
            logger.warning("AI metadata failed for %s: %s", reel_db_id, exc)

    await publish_queue.mark_job_stage(job["id"], "publishing")

    # Set YouTube metadata
    title = (ai_result or {}).get("title") or reel.get("caption") or "TikTok video"
    description = (ai_result or {}).get("description") or ""
    hashtags = (ai_result or {}).get("hashtags_json") or "[]"

    await publications.set_publication_ai_content(
        pub_id, title, description, hashtags,
        ai_model=(ai_result or {}).get("model"),
    )

    # Upload to YouTube
    youtube_video_id = await publish_video_to_youtube(
        destination_id, video_path, title, description,
        hashtags, reel.get("thumbnail_url"),
    )

    await publications.mark_scheduled(pub_id, youtube_video_id)
    await reels.mark_reel_scheduled(reel_db_id, youtube_video_id)
    await publish_queue.mark_job_stage(job["id"], "done")
    logger.info("Published reel %s -> YouTube video %s", reel_db_id, youtube_video_id)


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
