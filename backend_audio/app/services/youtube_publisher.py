"""YouTube publisher: resumable upload + captions, idempotent, retry-bounded."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("backend-audio.publish")

DESTINATION_REQUIRED = "YOUTUBE_DESTINATION_REQUIRED"
ALREADY_PUBLISHED = "ALREADY_PUBLISHED"
UPLOAD_FAILED = "YOUTUBE_UPLOAD_FAILED"
CAPTION_FAILED = "CAPTION_UPLOAD_FAILED"
DISCLOSURE_MANUAL = "AI_DISCLOSURE_REQUIRES_MANUAL_REVIEW"

MAX_RETRIES = 3
_CHUNK_SIZE = 8 * 1024 * 1024


class PublisherError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def build_metadata(title: str, description: str = "",
                   hashtags: list[str] | None = None) -> dict[str, Any]:
    tags = " ".join(hashtags or [])
    desc = (description or "").strip()
    if tags and tags not in desc:
        desc = f"{desc}\n\n{tags}".strip()
    return {"title": (title or "Untitled").strip()[:100],
            "description": desc[:5000]}


def _youtube_client(refresh_token: str):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    from app.config import settings

    creds = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube"],
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _blocking_upload(refresh_token: str, path: Path, metadata: dict,
                     privacy: str) -> str:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    youtube = _youtube_client(refresh_token)
    body = {"snippet": {"title": metadata["title"],
                        "description": metadata["description"],
                        "categoryId": "22"},
            "status": {"privacyStatus": privacy,
                       "selfDeclaredMadeForKids": False}}
    media = MediaFileUpload(str(path), chunksize=_CHUNK_SIZE, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body,
                                      media_body=media)
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = None
            while response is None:
                _, response = request.next_chunk()
            video_id = (response or {}).get("id")
            if not video_id:
                raise PublisherError(UPLOAD_FAILED, "YouTube returned no video id.")
            return video_id
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            last_error = exc
            if status in (500, 502, 503, 504) and attempt < MAX_RETRIES:
                continue
            raise PublisherError(
                UPLOAD_FAILED, f"YouTube upload HTTP {status}: {exc}"[:300])
        except PublisherError:
            raise
        except Exception as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                continue
            raise PublisherError(UPLOAD_FAILED,
                                 f"Upload error: {type(exc).__name__}.")
    raise PublisherError(UPLOAD_FAILED, f"Upload failed: {last_error}."[:300])


def _blocking_caption_upload(refresh_token: str, video_id: str, srt_path: Path,
                             language: str = "vi") -> None:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    youtube = _youtube_client(refresh_token)
    media = MediaFileUpload(str(srt_path), mimetype="application/x-subrip",
                            resumable=False)
    try:
        youtube.captions().insert(
            part="snippet", body={"snippet": {"videoId": video_id,
                                              "language": language,
                                              "name": "",
                                              "isDraft": False}},
            media_body=media).execute()
    except HttpError as exc:
        raise PublisherError(CAPTION_FAILED,
                             f"Caption upload HTTP {getattr(exc.resp, 'status', '?')}.")
    except Exception as exc:
        raise PublisherError(CAPTION_FAILED, f"Caption error: {type(exc).__name__}.")


async def publish_final(
    *,
    job: dict[str, Any],
    video_path: Path,
    title: str,
    description: str = "",
    hashtags: list[str] | None = None,
    srt_path: Path | None = None,
    captions_required: bool = False,
) -> dict[str, Any]:
    """Upload a finished MP4 (+ optional SRT captions). Idempotent per job."""
    from app.db.repositories import jobs as jobs_repo
    from app.db.repositories import youtube as yt_repo
    from app.services.youtube_oauth import OAuthError, load_credentials

    job_id = job["id"]
    fresh = jobs_repo.get_job(job_id) or job
    if fresh.get("youtube_video_id"):
        return {"youtube_video_id": fresh["youtube_video_id"], "already": True}

    pipeline_id = job.get("pipeline_id") or ""
    dest = yt_repo.resolve_destination_for_job(pipeline_id, job)
    if dest is None:
        raise PublisherError(DESTINATION_REQUIRED,
                             "No connected YouTube destination for this pipeline.")
    try:
        creds = load_credentials(dest["id"])
    except OAuthError as exc:
        raise PublisherError(DESTINATION_REQUIRED, str(exc))

    metadata = build_metadata(title, description, hashtags)
    privacy = "public"  # policy: PUBLIC unless destination says otherwise
    if (dest.get("visibility") or "public") in ("unlisted", "private"):
        privacy = dest["visibility"]
    video_id = await asyncio.to_thread(_blocking_upload, creds["refresh_token"],
                                       video_path, metadata, privacy)
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"
    jobs_repo.update_job(job_id, youtube_video_id=video_id)

    caption_state = "skipped"
    if srt_path is not None and srt_path.exists():
        try:
            await asyncio.to_thread(_blocking_caption_upload, creds["refresh_token"],
                                    video_id, srt_path)
            caption_state = "uploaded"
        except PublisherError as exc:
            caption_state = "failed"
            if captions_required:
                raise
            logger.warning("caption upload failed (non-blocking): %s", exc)
    return {"youtube_video_id": video_id, "youtube_url": youtube_url,
            "privacy": privacy, "captions": caption_state,
            "disclosure": DISCLOSURE_MANUAL}
