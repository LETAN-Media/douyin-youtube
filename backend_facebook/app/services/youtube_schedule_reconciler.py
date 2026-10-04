"""YouTube scheduled-publication reconciler (Task 10).

For publications whose status is 'scheduled' and whose scheduled_publish_at
has arrived (or passed), verify the YouTube video's real privacyStatus.
If YouTube reports the video as public, mark the publication (and its reel)
as published. Leave scheduled videos alone. Handle deleted/missing videos
with a safe terminal status.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ..config import settings
from ..db.repositories import destinations, publications, reels
from .facebook_youtube_publisher import (
    AUTH_FAILED,
    NETWORK_ERROR,
    QUOTA_EXCEEDED,
    UPLOAD_FAILED,
    YouTubePublisherError,
    load_destination_credentials_async,
    refresh_if_needed,
)

logger = logging.getLogger("backend-facebook.youtube-reconciler")

_RECONCILE_LOOKAHEAD = timedelta(minutes=10)
_RECONCILE_LIMIT = 20


class ReconcileError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


async def _load_credentials(destination_id: str) -> Any:
    credentials = await load_destination_credentials_async(destination_id)
    return await refresh_if_needed(destination_id, credentials)


def _build_youtube_client(credentials: Any) -> Any:
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


async def _fetch_youtube_video(youtube: Any, video_id: str) -> dict[str, Any] | None:
    request = youtube.videos().list(part="status,snippet", id=video_id)
    resp = request.execute()
    items = resp.get("items") or []
    return items[0] if items else None


async def _mark_publication_published(publication_id: str, youtube_video_id: str) -> None:
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    await publications.mark_published(publication_id, youtube_video_id)
    pub = await publications.get_publication(publication_id)
    if pub and pub.get("reel_db_id"):
        await reels.update_reel_status(pub["reel_db_id"], "published")


async def reconcile_due_scheduled_publications(limit: int = _RECONCILE_LIMIT) -> dict[str, int]:
    """Reconcile scheduled publications whose publishAt has arrived.

    Returns counters: checked, published, left_scheduled, errors.
    """
    now_utc = datetime.now(timezone.utc)
    cutoff = (now_utc + _RECONCILE_LOOKAHEAD).strftime("%Y-%m-%dT%H:%M:%SZ")
    candidates = await publications.list_due_scheduled_publications(limit=limit)

    counts = {"checked": 0, "published": 0, "left_scheduled": 0, "errors": 0}
    for pub in candidates:
        counts["checked"] += 1
        publication_id = pub["id"]
        destination_id = pub.get("destination_id")
        youtube_video_id = pub.get("youtube_video_id")
        if not destination_id or not youtube_video_id:
            counts["errors"] += 1
            continue
        try:
            credentials = await _load_credentials(destination_id)
            youtube = _build_youtube_client(credentials)
            video = await _fetch_youtube_video(youtube, youtube_video_id)
        except YouTubePublisherError as exc:
            logger.warning("reconcile auth/quota for %s: %s", publication_id, exc.code)
            counts["errors"] += 1
            continue
        except Exception as exc:
            logger.warning("reconcile unexpected for %s: %s", publication_id, exc)
            counts["errors"] += 1
            continue

        if video is None:
            logger.warning("reconcile missing YouTube video %s for publication %s", youtube_video_id, publication_id)
            counts["errors"] += 1
            continue

        status_block = video.get("status") or {}
        privacy = (status_block.get("privacyStatus") or "").lower()
        if privacy == "public":
            try:
                await _mark_publication_published(publication_id, youtube_video_id)
                counts["published"] += 1
            except Exception as exc:
                logger.exception("reconcile mark published failed for %s", publication_id)
                counts["errors"] += 1
        else:
            counts["left_scheduled"] += 1

    return counts
