"""YouTube scheduled-publish reconciliation.

Checks YouTube for scheduled videos that have completed their processing
and marks the corresponding publications/reels as published.
"""

import asyncio
import logging
import time
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from ..config import settings
from ..db.repositories import publications, reels
from .youtube_publisher import _get_credentials

logger = logging.getLogger("backend-tiktok.services.youtube_reconciler")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


async def reconciler_loop(stop_event: asyncio.Event) -> None:
    """Poll YouTube for scheduled video status and reconcile."""
    logger.info("TikTok YouTube reconciler started")
    poll = settings.tiktok_reconcile_poll_seconds

    while not stop_event.is_set():
        try:
            await _reconcile_ready()
        except Exception as exc:
            logger.exception("reconciler error: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll)
            break
        except asyncio.TimeoutError:
            continue

    logger.info("TikTok YouTube reconciler stopped")


async def _reconcile_ready() -> None:
    """Check publications in 'scheduled' state and verify on YouTube."""
    from ..db.client import execute

    res = await execute(
        """
        SELECT id, reel_db_id, destination_id, youtube_video_id, scheduled_publish_at
        FROM tiktok_publications
        WHERE status = 'scheduled' AND youtube_video_id IS NOT NULL
        LIMIT 50
        """
    )
    for row in res.rows:
        pub_id, reel_db_id, dest_id, yt_video_id, _ = row
        try:
            creds = await _get_credentials(dest_id)
            status = await _check_youtube_video(creds, yt_video_id)
            if status == "processed":
                await publications.mark_published(pub_id, yt_video_id, scheduled=True)
                await reels.mark_reel_published(reel_db_id, yt_video_id)
                logger.info("Reconciled publication %s -> published on YouTube", pub_id)
        except Exception as exc:
            logger.warning("Reconcile check failed for %s: %s", pub_id, exc)


async def _check_youtube_video(creds: Credentials, video_id: str) -> str | None:
    loop = asyncio.get_running_loop()

    def _check() -> str:
        service = build("youtube", "v3", credentials=creds)
        resp = service.videos().list(
            part="status,contentDetails",
            id=video_id,
        ).execute()
        items = resp.get("items", [])
        if not items:
            return "not_found"
        status = items[0].get("status", {})
        if status.get("privacyStatus") == "published" or status.get("uploadStatus") == "processed":
            return "processed"
        return status.get("uploadStatus", "status_check")

    return await loop.run_in_executor(None, _check)
