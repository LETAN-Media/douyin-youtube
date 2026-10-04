"""YouTube uploader bound to ONE Facebook destination (Task 7B).

Credentials come only from youtube_credentials[destination_id]; refresh
persists back to the same destination. Resumable upload, 8 MiB chunks,
limited retries on 5xx/network only. No tokens in errors or logs.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

from ..db.repositories import youtube_auth

logger = logging.getLogger("backend-facebook.youtube-publisher")

AUTH_FAILED = "YOUTUBE_AUTH_FAILED"
QUOTA_EXCEEDED = "YOUTUBE_QUOTA_EXCEEDED"
UPLOAD_FAILED = "YOUTUBE_UPLOAD_FAILED"
NETWORK_ERROR = "YOUTUBE_NETWORK_ERROR"

VALID_VISIBILITIES = ("public", "private", "unlisted")

_CHUNK_SIZE = 8 * 1024 * 1024
_MAX_RETRIES = 6
_MAX_BACKOFF_S = 30


class YouTubePublisherError(Exception):
    """Typed publisher error. Never carries tokens or credentials."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_visibility(visibility: str | None) -> str:
    """Reject bad visibility config instead of publishing with the wrong one."""
    value = (visibility or "").strip().lower()
    if value not in VALID_VISIBILITIES:
        raise YouTubePublisherError(
            UPLOAD_FAILED, f"Invalid visibility: {visibility!r}."
        )
    return value


def build_metadata(
    *, title: str | None, description: str | None, reel_id: str, reel_url: str | None,
    visibility: str,
) -> tuple[str, str]:
    """Temporary rule (no AI yet): caption or fallback, hard YouTube limits."""
    clean_title = (title or "").strip()
    final_title = (clean_title or f"Facebook Reel {reel_id}")[:100]
    parts = []
    clean_desc = (description or "").strip()
    if clean_desc:
        parts.append(clean_desc)
    if reel_url:
        parts.append(f"Source: {reel_url}")
    return final_title, "\n\n".join(parts)[:5000]


async def load_destination_credentials_async(destination_id: str) -> Any:
    """Parse this destination's own credentials. Never falls back elsewhere."""
    from google.oauth2.credentials import Credentials

    raw = await youtube_auth.get_credentials(destination_id)
    if not raw:
        raise YouTubePublisherError(AUTH_FAILED, "Destination has no YouTube credentials.")
    try:
        data = json.loads(raw)
    except Exception:
        raise YouTubePublisherError(AUTH_FAILED, "Stored YouTube credentials are corrupt.")
    return Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes"),
    )


def load_destination_credentials(destination_id: str) -> Any:
    """Sync wrapper for non-async callers."""
    import asyncio

    return asyncio.run(load_destination_credentials_async(destination_id))


async def refresh_if_needed(destination_id: str, credentials: Any) -> Any:
    """Refresh an expired access token and persist it to the SAME destination."""
    import asyncio

    if not getattr(credentials, "expired", False):
        return credentials
    if not getattr(credentials, "refresh_token", None):
        raise YouTubePublisherError(AUTH_FAILED, "YouTube refresh token is missing.")
    from google.auth.transport.requests import Request as GoogleRequest

    try:
        await asyncio.to_thread(credentials.refresh, GoogleRequest())
    except Exception as exc:
        raise YouTubePublisherError(AUTH_FAILED, f"YouTube token refresh failed: {type(exc).__name__}.")
    try:
        existing = await youtube_auth.get_credentials(destination_id)
        data = json.loads(existing) if existing else {}
    except Exception:
        data = {}
    data["token"] = credentials.token
    await youtube_auth.save_credentials(destination_id, json.dumps(data))
    return credentials


def _classify_http_error(status_code: int, reason: str) -> YouTubePublisherError:
    lowered = (reason or "").lower()
    if status_code == 401:
        return YouTubePublisherError(AUTH_FAILED, "YouTube rejected the credentials (401).")
    if status_code == 403 and ("quota" in lowered or "rate" in lowered or "limit" in lowered):
        return YouTubePublisherError(QUOTA_EXCEEDED, "YouTube quota exceeded (403).")
    if status_code in (500, 502, 503, 504):
        return YouTubePublisherError(NETWORK_ERROR, f"YouTube transient error ({status_code}).")
    return YouTubePublisherError(UPLOAD_FAILED, f"YouTube rejected the upload ({status_code}).")


def _is_retryable_status(status_code: int) -> bool:
    return status_code in (500, 502, 503, 504)


def upload_video(
    credentials: Any,
    file_path: Path | str,
    title: str,
    description: str,
    visibility: str,
    *,
    youtube_factory: Callable[..., Any] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> str:
    """Blocking resumable upload. Caller runs it in a thread (never the loop).

    Takes an already-loaded destination Credentials object (loaded + refreshed
    by the worker). Returns the YouTube video ID. Raises YouTubePublisherError.
    """
    path = Path(file_path)
    if not path.exists():
        raise YouTubePublisherError(UPLOAD_FAILED, "Video file does not exist.")
    privacy = validate_visibility(visibility)

    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    factory = youtube_factory or (lambda creds: build("youtube", "v3", credentials=creds, cache_discovery=False))
    youtube = factory(credentials)

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(str(path), chunksize=_CHUNK_SIZE, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    retry_count = 0
    while True:
        try:
            _, response = request.next_chunk()
            if response is None:
                continue
            video_id = (response or {}).get("id")
            if not video_id:
                raise YouTubePublisherError(UPLOAD_FAILED, "YouTube returned no video ID.")
            return video_id
        except YouTubePublisherError:
            raise
        except Exception as exc:
            from googleapiclient.errors import HttpError as _HttpError

            if isinstance(exc, _HttpError):
                status_code = exc.resp.status if exc.resp is not None else 0
                reason = ""
                try:
                    reason = exc.content.decode("utf-8", "replace") if exc.content else ""
                except Exception:
                    reason = ""
                if _is_retryable_status(status_code):
                    retry_count += 1
                    if retry_count > _MAX_RETRIES:
                        raise YouTubePublisherError(
                            NETWORK_ERROR, "YouTube upload failed after retries."
                        )
                    sleep_fn(min(2**retry_count, _MAX_BACKOFF_S))
                    continue
                raise _classify_http_error(status_code, reason)
            retry_count += 1
            if retry_count > _MAX_RETRIES:
                raise YouTubePublisherError(
                    NETWORK_ERROR, f"YouTube upload interrupted: {type(exc).__name__}."
                )
            sleep_fn(min(2**retry_count, _MAX_BACKOFF_S))
