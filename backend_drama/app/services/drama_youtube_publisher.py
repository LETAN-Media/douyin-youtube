"""YouTube publisher for drama (resumable upload, progress, retry).

Ported from the proven backend_facebook uploader, adapted to drama
credentials/destinations. Blocking calls run in a thread, never the loop.

- Resumable upload with real byte progress (persisted to the job row).
- Automatic token refresh via drama credentials (old refresh preserved).
- Bounded retries on transient errors; typed errors otherwise.
- Idempotent: a job that already has a youtube_video_id is never
  re-uploaded (checked before AND after upload against the row).
- A video is marked published only on confirmed success; scheduled
  uploads stay scheduled until YouTube confirms.
"""

import logging
import time
import json
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("backend-drama-youtube")

AUTH_FAILED = "YOUTUBE_AUTH_FAILED"
UPLOAD_FAILED = "YOUTUBE_UPLOAD_FAILED"
NETWORK_ERROR = "YOUTUBE_NETWORK_ERROR"
QUOTA_EXCEEDED = "YOUTUBE_QUOTA_EXCEEDED"
DESTINATION_REQUIRED = "YOUTUBE_DESTINATION_REQUIRED"

_CHUNK_SIZE = 8 * 1024 * 1024
_MAX_RETRIES = 5
_MAX_BACKOFF_S = 30.0


class YouTubePublisherError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_visibility(visibility: str | None) -> str:
    v = (visibility or "public").strip().lower()
    if v not in ("public", "unlisted", "private"):
        raise YouTubePublisherError(
            UPLOAD_FAILED, f"Invalid visibility: {visibility!r}."
        )
    return v


def validate_publish_at(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    from datetime import datetime, timezone

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise YouTubePublisherError(UPLOAD_FAILED, f"Invalid publish_at: {text[:40]}.") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if (dt - now).total_seconds() < 60:
        raise YouTubePublisherError(UPLOAD_FAILED, "publish_at must be in the future.")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_metadata(*, title: str, description: str = "",
                   hashtags: list[str] | None = None,
                   visibility: str = "public",
                   publish_at: str | None = None) -> dict[str, Any]:
    privacy = validate_visibility(visibility)
    validated_at = validate_publish_at(publish_at)
    tags = " ".join(hashtags or [])
    desc = (description or "").strip()
    if tags and tags not in desc:
        desc = f"{desc}\n\n{tags}".strip()
    status_body: dict[str, Any] = {
        "privacyStatus": privacy,
        "selfDeclaredMadeForKids": False,
    }
    if validated_at:
        status_body["privacyStatus"] = "private"
        status_body["publishAt"] = validated_at
    return {
        "snippet": {
            "title": (title or "Untitled").strip()[:100],
            "description": desc[:5000],
            "categoryId": "22",
        },
        "status": status_body,
    }


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
    metadata: dict[str, Any],
    *,
    youtube_factory: Callable[..., Any] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> str:
    """Blocking resumable upload. Returns the YouTube video ID."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    path = Path(file_path)
    if not path.exists() or path.stat().st_size <= 0:
        raise YouTubePublisherError(UPLOAD_FAILED, "Video file does not exist.")
    total = path.stat().st_size
    factory = youtube_factory or (
        lambda creds: build("youtube", "v3", credentials=creds, cache_discovery=False)
    )
    youtube = factory(credentials)
    media = MediaFileUpload(str(path), chunksize=_CHUNK_SIZE, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=metadata, media_body=media)

    retry_count = 0
    while True:
        try:
            progress, response = request.next_chunk()
            if on_progress is not None:
                try:
                    sent = progress.resumable_progress if progress else 0
                    on_progress(int(sent or 0), total)
                except Exception:
                    pass
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
                    sleep_fn(min(2 ** retry_count, _MAX_BACKOFF_S))
                    continue
                raise _classify_http_error(status_code, reason)
            retry_count += 1
            if retry_count > _MAX_RETRIES:
                raise YouTubePublisherError(
                    NETWORK_ERROR, f"YouTube upload interrupted: {type(exc).__name__}."
                )
            sleep_fn(min(2 ** retry_count, _MAX_BACKOFF_S))


async def publish_job_final(
    job: dict[str, Any],
    final_path: Path | str,
    *,
    title: str | None = None,
    description: str = "",
    hashtags: list[str] | None = None,
    visibility: str = "public",
    publish_at: str | None = None,
    youtube_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Upload a finished final.mp4 for a series job (orchestrator hook).

    Resolves the pipeline destination, enforces YOUTUBE_DESTINATION_REQUIRED,
    reconciles before upload (no duplicate when a video id already exists),
    persists progress + video id. Returns {"youtube_video_id": ...}.
    """
    import asyncio

    from ..db.repositories import processing as proc_repo
    from ..db.repositories import youtube as yt_repo
    from .drama_youtube_oauth import load_credentials

    job_id = job["id"]
    fresh = proc_repo.get_job(job_id) or job
    if fresh.get("youtube_video_id"):
        return {"youtube_video_id": fresh["youtube_video_id"], "already": True}

    pipeline_id = job.get("pipeline_id") or ""
    settings = proc_repo.get_settings(pipeline_id)
    destination_id = settings.get("youtube_destination_id")
    if not destination_id:
        raise YouTubePublisherError(
            DESTINATION_REQUIRED,
            "Chưa chọn YouTube destination cho pipeline này.",
        )
    destination = yt_repo.get_destination(destination_id)
    if destination is None or not destination.get("connected"):
        raise YouTubePublisherError(
            DESTINATION_REQUIRED,
            "YouTube destination chưa được kết nối.",
        )
    # ---- AI metadata (one set per final video; snapshot on the job) ----
    try:
        from .drama_ai_metadata import (
            AI_DISABLED_FOR_PIPELINE,
            CONFIG_MISSING,
            MetadataError,
            ensure_drama_ai_metadata,
        )

        try:
            ai_result = await ensure_drama_ai_metadata(job)
        except MetadataError as exc:
            if exc.code in (AI_DISABLED_FOR_PIPELINE, CONFIG_MISSING):
                ai_result = None  # AI off -> keep existing manual/default metadata
            else:
                proc_repo.update_job(
                    job_id,
                    ai_metadata_status="failed",
                    last_error_code="AI_METADATA_FAILED",
                    last_error_message=str(exc)[:500],
                )
                raise YouTubePublisherError("AI_METADATA_FAILED", str(exc)[:500])
        if ai_result is not None:
            title = ai_result.metadata.title
            description = ai_result.metadata.description
            hashtags = ai_result.metadata.hashtags
            proc_repo.update_job(
                job_id,
                ai_title=ai_result.metadata.title,
                ai_description=ai_result.metadata.description,
                ai_hashtags_json=json.dumps(
                    ai_result.metadata.hashtags, ensure_ascii=False
                ),
                ai_metadata_status="cached" if ai_result.cached else "generated",
            )
    except YouTubePublisherError:
        raise
    except Exception as exc:  # noqa: BLE001 - never block upload on snapshot issues
        logger.warning("drama AI metadata snapshot failed: %s", type(exc).__name__)
    metadata = build_metadata(
        title=title or f"Drama EP {job.get('episode_start')}-{job.get('episode_end')}",
        description=description, hashtags=hashtags,
        visibility=destination.get("visibility") or visibility,
        publish_at=publish_at,
    )
    credentials = await load_credentials(destination_id)

    def _report(sent: int, total: int) -> None:
        try:
            proc_repo.update_job(
                job_id, status="uploading",
                upload_progress=(sent / total) if total else 0.0,
            )
        except Exception:
            pass

    video_id = await asyncio.to_thread(
        upload_video, credentials, final_path, metadata,
        youtube_factory=youtube_factory,
        on_progress=lambda sent, total: _report(sent, total),
        sleep_fn=lambda s: time.sleep(min(s, 5.0)),
    )
    # Reconcile after upload: only one video id per job, ever.
    check = proc_repo.get_job(job_id) or {}
    if check.get("youtube_video_id") and check["youtube_video_id"] != video_id:
        logger.warning("job %s already has video %s; keeping original", job_id, check["youtube_video_id"])
        return {"youtube_video_id": check["youtube_video_id"], "already": True}
    proc_repo.update_job(job_id, youtube_video_id=video_id, upload_progress=1.0)
    return {"youtube_video_id": video_id}
