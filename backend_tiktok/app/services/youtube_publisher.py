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


class YouTubeQuotaExceededError(Exception):
    pass


async def _get_credentials(destination_id: str) -> Credentials:
    import asyncio
    from google.auth.transport.requests import Request
    from ..config import settings

    row = await youtube_auth.get_credentials(destination_id)
    if row is None:
        raise RuntimeError("YouTube credentials not found for destination")
    data = jsonlib.loads(row["credentials_json"])
    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri") or "https://oauth2.googleapis.com/token",
        client_id=data.get("client_id") or settings.google_client_id,
        client_secret=data.get("client_secret") or settings.google_client_secret,
        scopes=data.get("scopes") or [
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly",
        ],
    )
    if not creds.valid or creds.expired:
        if creds.refresh_token:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(_executor, creds.refresh, Request())
                data["token"] = creds.token
                await youtube_auth.save_credentials(destination_id, jsonlib.dumps(data))
                logger.info("Successfully refreshed OAuth token for destination %s", destination_id)
            except Exception as exc:
                logger.warning("Failed to refresh OAuth token for destination %s: %s", destination_id, exc)
    return creds


async def publish_video_to_youtube(
    destination_id: str,
    video_path: Any,
    title: str,
    description: str,
    hashtags_json: str,
    thumbnail_url: str | None = None,
    schedule_seconds: int | None = None,
    is_shorts: bool = False,
) -> str:
    """Upload a video to YouTube and return the video ID."""
    creds = await _get_credentials(destination_id)
    return await _do_upload(
        creds, destination_id, video_path, title, description,
        hashtags_json, thumbnail_url, schedule_seconds, is_shorts=is_shorts,
    )


async def _do_upload(
    creds: Credentials,
    destination_id: str,
    video_path: Any,
    title: str,
    description: str,
    hashtags_json: str,
    thumbnail_url: str | None,
    schedule_seconds: int | None,
    is_shorts: bool = False,
) -> str:
    import asyncio
    import time
    from googleapiclient.errors import HttpError

    loop = asyncio.get_running_loop()

    def _sync_upload() -> str:
        service = build("youtube", "v3", credentials=creds)
        hashtags: list[str] = []
        if hashtags_json:
            try:
                hashtags = jsonlib.loads(hashtags_json)
            except (ValueError, TypeError):
                pass

        full_desc = description or ""
        if hashtags:
            full_desc = (full_desc + "\n\n" + " ".join(hashtags)).strip()

        # If shorts format, ensure #Shorts is present for optimal recognition
        upload_title = title or "TikTok Video"
        if is_shorts:
            if "#Shorts" not in upload_title and "#shorts" not in upload_title:
                if len(upload_title) <= 90:
                    upload_title = f"{upload_title} #Shorts"
            if "#Shorts" not in full_desc and "#shorts" not in full_desc:
                full_desc = f"{full_desc}\n#Shorts".strip()

        body: dict[str, Any] = {
            "snippet": {
                "title": _truncate(upload_title, 100),
                "description": _truncate(full_desc, 5000),
                "tags": [h.lstrip("#") for h in hashtags][:25] if hashtags else [],
            },
            "status": {
                "privacyStatus": "public",
                "madeForKids": False,
            },
        }

        if schedule_seconds and schedule_seconds > 0:
            publish_at = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + schedule_seconds)
            )
            body["status"]["privacyStatus"] = "private"
            body["status"]["publishAt"] = publish_at
            body["status"]["selfDeclaredMadeForKids"] = False

        media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)

        try:
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

            if thumbnail_url and not is_shorts:
                try:
                    _set_thumbnail(service, video_id, thumbnail_url)
                except Exception as exc:
                    logger.warning("Failed to set thumbnail for %s: %s", video_id, exc)

            return video_id or ""
        except HttpError as err:
            err_str = str(err).lower()
            if "quotaexceeded" in err_str or "uploadlimitexceeded" in err_str:
                raise YouTubeQuotaExceededError(f"YouTube upload quota exceeded: {err}") from err
            raise
        finally:
            try:
                if os.path.exists(str(video_path)):
                    os.unlink(str(video_path))
            except OSError:
                pass

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
