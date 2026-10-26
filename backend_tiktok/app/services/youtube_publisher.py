"""YouTube video publisher — reused from backend_facebook pattern."""

import json as jsonlib
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from ..db.repositories import youtube_auth

logger = logging.getLogger("backend-tiktok.services.youtube_publisher")

_executor = ThreadPoolExecutor(max_workers=2)


async def _get_credentials(destination_id: str) -> Credentials:
    row = await youtube_auth.get_credentials(destination_id)
    if row is None:
        raise RuntimeError("YouTube credentials not found for destination")
    data = jsonlib.loads(row["credentials_json"])
    return Credentials(
        token=data["token"],
        refresh_token=data.get("refresh_token"),
        token_uri=data["token_uri"],
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        scopes=data["scopes"],
    )


async def publish_video_to_youtube(
    destination_id: str,
    video_path: Any,
    title: str,
    description: str,
    hashtags_json: str,
    thumbnail_url: str | None = None,
    schedule_seconds: int | None = None,
) -> str:
    """Upload a video to YouTube and return the video ID."""
    creds = await _get_credentials(destination_id)
    return await _do_upload(creds, destination_id, video_path, title, description,
                            hashtags_json, thumbnail_url, schedule_seconds)


async def _do_upload(
    creds: Credentials,
    destination_id: str,
    video_path: Any,
    title: str,
    description: str,
    hashtags_json: str,
    thumbnail_url: str | None,
    schedule_seconds: int | None,
) -> str:
    import asyncio
    import time

    loop = asyncio.get_running_loop()

    def _sync_upload() -> str:
        service = build("youtube", "v3", credentials=creds)
        hashtags: list[str] = []
        if hashtags_json:
            try:
                hashtags = jsonlib.loads(hashtags_json)
            except (ValueError, TypeError):
                pass

        full_desc = description
        if hashtags:
            full_desc = (full_desc + "\n\n" + " ".join(hashtags)).strip()

        body: dict[str, Any] = {
            "snippet": {
                "title": _truncate(title, 100),
                "description": _truncate(full_desc, 5000),
                "tags": [h.lstrip("#") for h in hashtags][:25] if hashtags else [],
            },
            "status": {
                "privacyStatus": "public",
                "madeForKids": False,
            },
        }

        if schedule_seconds:
            publish_at = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + schedule_seconds)
            )
            body["status"]["privacyStatus"] = "private"
            body["status"]["publishAt"] = publish_at
            body["status"]["selfDeclaredMadeForKids"] = False

        media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)

        request = service.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                logger.debug("Upload progress: %d%%", pct)

        video_id = response.get("id")
        logger.info("YouTube upload complete: %s", video_id)

        if thumbnail_url:
            try:
                _set_thumbnail(service, video_id, thumbnail_url)
            except Exception as exc:
                logger.warning("Failed to set thumbnail for %s: %s", video_id, exc)

        try:
            os.unlink(str(video_path))
        except OSError:
            pass

        return video_id or ""

    return await loop.run_in_executor(_executor, _sync_upload)


def _truncate(text: str | None, limit: int) -> str | None:
    if not text:
        return None
    return text[:limit] if len(text) > limit else text


def _set_thumbnail(service, video_id: str, thumbnail_url: str) -> None:
    import httpx

    resp = httpx.get(thumbnail_url)
    thumb_path = f"/tmp/tiktok_thumb_{video_id}.jpg"
    with open(thumb_path, "wb") as f:
        f.write(resp.content)
    service.thumbnails().set(
        videoId=video_id,
        media_body=MediaFileUpload(thumb_path),
    ).execute()
    os.unlink(thumb_path)
