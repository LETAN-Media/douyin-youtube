import json
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppSetting, Destination, OAuthState, Pipeline


logger = logging.getLogger("douyin-youtube-youtube")


#: Required to read comments and post replies (comments.insert).
#: Channels authorised before this scope was added must reconnect.
YOUTUBE_FORCE_SSL_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"

#: Required to read OWNED channel analytics (YouTube Analytics API).
#: No monetary/revenue scope is requested.
YOUTUBE_ANALYTICS_READONLY_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    YOUTUBE_FORCE_SSL_SCOPE,
    YOUTUBE_ANALYTICS_READONLY_SCOPE,
]

GLOBAL_TOKEN_SETTING_KEY = "youtube_credentials"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def validate_google_config() -> None:
    if not settings.google_client_id:
        raise RuntimeError(
            "GOOGLE_CLIENT_ID chưa được cấu hình"
        )

    if not settings.google_client_secret:
        raise RuntimeError(
            "GOOGLE_CLIENT_SECRET chưa được cấu hình"
        )


def client_config() -> dict:
    validate_google_config()

    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": (
                "https://accounts.google.com/o/oauth2/v2/auth"
            ),
            "token_uri": (
                "https://oauth2.googleapis.com/token"
            ),
            "redirect_uris": [
                settings.youtube_callback_url
            ],
        }
    }


def save_setting(
    db: Session,
    key: str,
    value: str,
) -> None:
    row = db.get(
        AppSetting,
        key,
    )

    if row is None:
        row = AppSetting(
            key=key,
            value=value,
        )
        db.add(row)
    else:
        row.value = value

    db.commit()


def read_setting(
    db: Session,
    key: str,
) -> str | None:
    row = db.get(
        AppSetting,
        key,
    )

    if row is None:
        return None

    return row.value


def create_oauth_url(
    db: Session,
    pipeline_id: str | None = None,
    destination_id: str | None = None,
) -> str:
    validate_google_config()

    state = secrets.token_urlsafe(48)

    resolved_destination_id = destination_id

    if not resolved_destination_id and pipeline_id:
        destination = db.execute(
            select(Destination)
            .where(Destination.pipeline_id == pipeline_id)
            .where(Destination.platform == "youtube")
            .limit(1)
        ).scalar_one_or_none()

        if destination:
            resolved_destination_id = destination.id

    db.add(
        OAuthState(
            state=state,
            pipeline_id=pipeline_id,
            destination_id=resolved_destination_id,
            expires_at=(
                utcnow()
                + timedelta(minutes=15)
            ),
        )
    )

    db.commit()

    flow = Flow.from_client_config(
        client_config(),
        scopes=SCOPES,
        state=state,
        autogenerate_code_verifier=False,
    )

    flow.redirect_uri = (
        settings.youtube_callback_url
    )

    authorization_url, _ = (
        flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent select_account",
        )
    )

    return authorization_url


def complete_oauth(
    db: Session,
    state: str,
    authorization_response: str,
    pipeline_id: str | None = None,
    destination_id: str | None = None,
) -> None:
    state_row = db.get(
        OAuthState,
        state,
    )

    if state_row is None:
        raise RuntimeError(
            "OAuth state không tồn tại"
        )

    expires_at = state_row.expires_at

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(
            tzinfo=timezone.utc
        )

    if expires_at < utcnow():
        db.delete(state_row)
        db.commit()

        raise RuntimeError(
            "OAuth state đã hết hạn"
        )

    resolved_destination_id = (
        destination_id or state_row.destination_id
    )
    resolved_pipeline_id = (
        pipeline_id or state_row.pipeline_id
    )

    old_refresh_token = None
    destination = None

    if resolved_destination_id:
        destination = db.get(
            Destination,
            resolved_destination_id,
        )
        if destination is not None and destination.credentials:
            try:
                old_refresh_token = (
                    json.loads(destination.credentials)
                    .get("refresh_token")
                )
            except Exception:
                old_refresh_token = None
    elif resolved_pipeline_id:
        pipeline = db.get(
            Pipeline,
            resolved_pipeline_id,
        )
        if pipeline is not None and pipeline.youtube_credentials:
            try:
                old_refresh_token = (
                    json.loads(pipeline.youtube_credentials)
                    .get("refresh_token")
                )
            except Exception:
                old_refresh_token = None
    else:
        existing = read_setting(
            db,
            GLOBAL_TOKEN_SETTING_KEY,
        )

        if existing:
            try:
                old_refresh_token = (
                    json.loads(existing)
                    .get("refresh_token")
                )
            except Exception:
                old_refresh_token = None

    flow = Flow.from_client_config(
        client_config(),
        scopes=SCOPES,
        state=state,
        autogenerate_code_verifier=False,
    )

    flow.redirect_uri = (
        settings.youtube_callback_url
    )

    flow.fetch_token(
        authorization_response=authorization_response
    )

    credentials = flow.credentials

    refresh_token = (
        credentials.refresh_token
        or old_refresh_token
    )

    data = {
        "token": credentials.token,
        "refresh_token": refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": (
            credentials.client_secret
        ),
        "scopes": list(
            credentials.scopes or SCOPES
        ),
    }

    token_json = json.dumps(data)

    youtube = build(
        "youtube",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )

    try:
        result = youtube.channels().list(
            part="id,snippet",
            mine=True,
        ).execute()
    except HttpError as exc:
        raise RuntimeError(
            f"YouTube API error khi kiểm tra kênh: {exc}"
        ) from exc

    channels = result.get("items", [])

    if not channels:
        raise RuntimeError(
            "Không tìm thấy kênh YouTube nào trên tài khoản này"
        )

    channel = channels[0]
    channel_id = channel["id"]
    channel_title = channel["snippet"]["title"]
    thumbnails = channel["snippet"].get("thumbnails", {})
    avatar_url = (
        thumbnails.get("default", {}).get("url")
        or thumbnails.get("medium", {}).get("url")
        or thumbnails.get("high", {}).get("url")
    )
    if avatar_url:
        data["avatar_url"] = avatar_url
    token_json = json.dumps(data)

    if resolved_destination_id:
        if destination is None:
            destination = db.get(
                Destination,
                resolved_destination_id,
            )
            if destination is None:
                raise RuntimeError(
                    "Destination không tồn tại khi lưu OAuth"
                )

        destination.credentials = token_json
        destination.external_account_id = channel_id
        destination.external_account_name = channel_title
        destination.connected = True
        db.commit()
        logger.info(
            "Saved YouTube OAuth for destination=%s",
            resolved_destination_id,
        )
    elif resolved_pipeline_id:
        if pipeline is None:
            pipeline = db.get(
                Pipeline,
                resolved_pipeline_id,
            )
            if pipeline is None:
                raise RuntimeError(
                    "Pipeline không tồn tại khi lưu OAuth"
                )

        pipeline.youtube_credentials = token_json
        pipeline.youtube_channel_id = channel_id
        pipeline.youtube_channel_title = channel_title
        pipeline.youtube_connected = True
        db.commit()
        logger.info(
            "Saved YouTube OAuth for pipeline=%s",
            resolved_pipeline_id,
        )
    else:
        save_setting(
            db,
            GLOBAL_TOKEN_SETTING_KEY,
            token_json,
        )
        logger.info(
            "Saved YouTube OAuth globally"
        )

    state_row = db.get(
        OAuthState,
        state,
    )

    if state_row:
        db.delete(state_row)
        db.commit()


def _load_from_json(
    raw: str | None,
) -> Credentials:
    if not raw:
        raise RuntimeError(
            "YouTube chưa được kết nối OAuth"
        )

    data = json.loads(raw)

    credentials = Credentials(
        token=data.get("token"),
        refresh_token=data.get(
            "refresh_token"
        ),
        token_uri=data.get(
            "token_uri"
        ),
        client_id=data.get(
            "client_id"
        ),
        client_secret=data.get(
            "client_secret"
        ),
        scopes=data.get(
            "scopes"
        ),
    )

    if credentials.expired:
        if not credentials.refresh_token:
            raise RuntimeError(
                "YouTube refresh token không tồn tại"
            )

        credentials.refresh(
            GoogleRequest()
        )

        data["token"] = (
            credentials.token
        )

    return credentials


def load_credentials(
    db: Session,
    pipeline_id: str | None = None,
    destination_id: str | None = None,
) -> Credentials:
    # Destination OAuth isolation: when a destination is specified, its own
    # credentials MUST be used. Never fall back to another destination,
    # pipeline-global or app-global token (would upload YouTube A with B's
    # credentials).
    if destination_id:
        destination = db.get(Destination, destination_id)
        raw = None
        if destination is not None:
            raw = destination.credentials
        if not raw:
            raise RuntimeError(
                "Destination YouTube chưa được kết nối OAuth "
                f"(destination_id={destination_id})"
            )
        credentials = _load_from_json(raw)
        # Persist refreshed access token back to this destination only.
        try:
            data = json.loads(raw)
            if credentials.token and data.get("token") != credentials.token:
                data["token"] = credentials.token
                destination.credentials = json.dumps(data)
                db.commit()
        except Exception:
            pass
        return credentials

    raw = None

    if pipeline_id:
        pipeline = db.get(Pipeline, pipeline_id)
        if pipeline is not None and pipeline.youtube_credentials:
            raw = pipeline.youtube_credentials

    if not raw:
        raw = read_setting(
            db,
            GLOBAL_TOKEN_SETTING_KEY,
        )

    return _load_from_json(raw)


def destination_oauth_ready(
    destination: Destination | None,
) -> tuple[bool, str | None]:
    """Check a Destination is ready for YouTube scheduling/upload.

    Returns (ready, reason). Reasons use scheduler reason codes.
    """
    if destination is None:
        return False, "DESTINATION_NOT_FOUND"
    if not destination.enabled:
        return False, "SCHEDULER_DISABLED"
    if (destination.platform or "").lower() != "youtube":
        return False, "UNSUPPORTED_PLATFORM"
    if not destination.connected:
        return False, "DESTINATION_NOT_CONNECTED"
    if not destination.credentials:
        return False, "DESTINATION_NOT_CONNECTED"
    try:
        data = json.loads(destination.credentials)
    except Exception:
        return False, "DESTINATION_NOT_CONNECTED"
    if not data.get("refresh_token"):
        return False, "DESTINATION_NOT_CONNECTED"
    return True, None


def granted_scopes(raw_credentials: str | None) -> list[str]:
    """Scopes saved with a destination's OAuth token (never a secret)."""
    if not raw_credentials:
        return []
    try:
        data = json.loads(raw_credentials)
    except Exception:
        return []
    scopes = data.get("scopes")
    if not isinstance(scopes, list):
        return []
    return [str(item) for item in scopes if item]


def destination_comment_scope_status(
    destination: Destination | None,
) -> tuple[bool, str | None]:
    """Can this destination read/reply to comments?

    Returns (ok, reason). A channel authorised before force-ssl was added
    MUST reconnect: an old refresh token does not silently gain the scope.
    """
    if destination is None:
        return False, "DESTINATION_NOT_FOUND"
    if not destination.credentials:
        return False, "YOUTUBE_REAUTH_REQUIRED"
    scopes = granted_scopes(destination.credentials)
    if not scopes:
        # Token predates scope recording: assume it lacks force-ssl rather
        # than risk a 403 mid-reply.
        return False, "YOUTUBE_SCOPE_MISSING"
    if YOUTUBE_FORCE_SSL_SCOPE in scopes:
        return True, None
    if any(str(s).endswith("youtube.force-ssl") for s in scopes):
        return True, None
    return False, "YOUTUBE_SCOPE_MISSING"


def destination_analytics_scope_status(
    destination: Destination | None,
) -> tuple[bool, str | None]:
    """Can this destination read OWNED channel analytics?

    Returns (ok, reason). Channels authorised before yt-analytics.readonly
    was added MUST reconnect (RECONNECT_REQUIRED): an old refresh token
    does not silently gain the scope. Never touches the channel otherwise.
    """
    if destination is None:
        return False, "DESTINATION_NOT_FOUND"
    if not destination.credentials:
        return False, "YOUTUBE_REAUTH_REQUIRED"
    scopes = granted_scopes(destination.credentials)
    if not scopes:
        # Token predates scope recording: assume analytics scope missing.
        return False, "RECONNECT_REQUIRED"
    if YOUTUBE_ANALYTICS_READONLY_SCOPE in scopes:
        return True, None
    if any(str(s).endswith("yt-analytics.readonly") for s in scopes):
        return True, None
    return False, "RECONNECT_REQUIRED"


def build_destination_client(
    db: Session,
    destination_id: str,
) -> tuple[Credentials, Any]:
    """YouTube API client bound to ONE destination's own OAuth token.

    Never falls back to another destination / pipeline / global token.
    """
    credentials = load_credentials(db, destination_id=destination_id)
    youtube = build(
        "youtube",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )
    return credentials, youtube


def youtube_connected(
    db: Session,
    pipeline_id: str | None = None,
) -> bool:
    if pipeline_id:
        pipeline = db.get(Pipeline, pipeline_id)
        if pipeline is not None:
            return bool(pipeline.youtube_connected)

    raw = read_setting(
        db,
        GLOBAL_TOKEN_SETTING_KEY,
    )

    if not raw:
        return False

    try:
        data = json.loads(raw)
    except Exception:
        return False

    return bool(
        data.get("refresh_token")
    )


def get_youtube_status(
    db: Session,
    pipeline_id: str | None = None,
    destination_id: str | None = None,
) -> dict:
    if destination_id:
        destination = db.get(Destination, destination_id)
        if destination is not None:
            return {
                "connected": destination.connected,
                "destination_id": destination.id,
                "pipeline_id": destination.pipeline_id,
                "channel_id": destination.external_account_id,
                "channel_title": destination.external_account_name,
            }
        return {
            "connected": False,
            "destination_id": destination_id,
        }

    connected = False
    channel_id = None
    channel_title = None

    if pipeline_id:
        pipeline = db.get(Pipeline, pipeline_id)
        if pipeline is not None:
            connected = bool(pipeline.youtube_credentials)
            channel_id = pipeline.youtube_channel_id
            channel_title = pipeline.youtube_channel_title
    else:
        raw = read_setting(
            db,
            GLOBAL_TOKEN_SETTING_KEY,
        )
        connected = bool(raw)

    return {
        "connected": connected,
        "pipeline_id": pipeline_id,
        "channel_id": channel_id,
        "channel_title": channel_title,
    }


def upload_video(
    db: Session,
    file_path: Path,
    title: str,
    description: str,
    privacy_status: str,
    pipeline_id: str | None = None,
    destination_id: str | None = None,
    publish_at: datetime | str | None = None,
    publish_mode: str | None = None,
) -> str:
    """Upload with native YouTube scheduling support.

    publish_mode: immediate | scheduled | private | unlisted.
    When scheduled, privacy_status is forced to private and publishAt (RFC3339
    UTC) is sent. publishAt is never sent for public/unlisted/private.
    """
    if not file_path.exists():
        raise RuntimeError(
            f"Không tìm thấy video: {file_path}"
        )

    credentials = load_credentials(
        db,
        pipeline_id=pipeline_id,
        destination_id=destination_id,
    )

    youtube = build(
        "youtube",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )

    # Resolve native scheduling status (never mutate caller args).
    from app.youtube_scheduling import (
        build_insert_status,
        ensure_utc,
        normalize_youtube_error,
        parse_publish_at,
        validate_scheduled_mode,
    )

    mode = (publish_mode or "").lower() or None
    if mode is None:
        # Backwards compat: infer from privacy_status.
        mode = {"public": "immediate", "private": "private", "unlisted": "unlisted"}.get(
            (privacy_status or "public").lower(), "immediate"
        )
    publish_at_utc = None
    if publish_at is not None:
        try:
            publish_at_utc = parse_publish_at(publish_at)
        except Exception as exc:
            raise RuntimeError(f"INVALID_PUBLISH_AT: {exc}") from exc
    try:
        validate_scheduled_mode(mode, publish_at_utc)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc

    try:
        status_body = build_insert_status(mode, publish_at_utc)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc

    body = {
        "snippet": {
            "title": title[:100],
            "description": (
                description[:5000]
            ),
            "categoryId": "22",
        },
        "status": {
            **status_body,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(file_path),
        chunksize=8 * 1024 * 1024,
        resumable=True,
    )

    request = (
        youtube.videos()
        .insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )
    )

    retry_count = 0
    max_retries = 6

    while True:
        try:
            _, response = (
                request.next_chunk()
            )

            if response is None:
                continue

            video_id = response.get(
                "id"
            )

            if not video_id:
                raise RuntimeError(
                    "YouTube không trả về video ID"
                )

            return video_id

        except HttpError as exc:
            status_code = (
                exc.resp.status
                if exc.resp
                else 0
            )

            retryable = status_code in {
                500,
                502,
                503,
                504,
            }

            if not retryable:
                from app.youtube_scheduling import normalize_youtube_error as _norm

                raise RuntimeError(
                    _norm(exc)
                    or (
                        f"YouTube API error "
                        f"{status_code}: {exc}"
                    )
                ) from exc

            retry_count += 1

            if retry_count > max_retries:
                raise RuntimeError(
                    "YouTube upload thất bại "
                    "sau nhiều lần retry"
                )

            time.sleep(
                min(
                    2 ** retry_count,
                    30,
                )
            )

        except (
            OSError,
            TimeoutError,
            ConnectionError,
        ) as exc:
            retry_count += 1

            if retry_count > max_retries:
                raise RuntimeError(
                    "Mất kết nối khi upload YouTube"
                ) from exc

            time.sleep(
                min(
                    2 ** retry_count,
                    30,
                )
            )


def _youtube_client_for_destination(db: Session, destination_id: str):
    _, youtube = build_destination_client(db, destination_id)
    return youtube


def update_video_schedule(
    db: Session,
    destination_id: str,
    youtube_video_id: str,
    new_publish_at: datetime | str,
) -> dict:
    """Change schedule: videos.update with privacyStatus=private + publishAt."""
    from app.youtube_scheduling import (
        build_reschedule_status,
        normalize_youtube_error,
        parse_publish_at,
        validate_publish_at,
    )

    publish_at_utc = parse_publish_at(new_publish_at)
    if publish_at_utc is None:
        raise RuntimeError("INVALID_PUBLISH_AT: new publish_at is required")
    try:
        validate_publish_at(publish_at_utc)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    youtube = _youtube_client_for_destination(db, destination_id)
    body = {"id": youtube_video_id, "status": build_reschedule_status(publish_at_utc)}
    try:
        return (
            youtube.videos()
            .update(part="status", body=body)
            .execute()
        )
    except HttpError as exc:
        raise RuntimeError(normalize_youtube_error(exc)) from exc


def publish_video_now(
    db: Session,
    destination_id: str,
    youtube_video_id: str,
) -> dict:
    """Scheduled -> Publish now: videos.update privacyStatus=public."""
    from app.youtube_scheduling import build_publish_now_status, normalize_youtube_error

    youtube = _youtube_client_for_destination(db, destination_id)
    body = {"id": youtube_video_id, "status": build_publish_now_status()}
    try:
        return (
            youtube.videos()
            .update(part="status", body=body)
            .execute()
        )
    except HttpError as exc:
        raise RuntimeError(normalize_youtube_error(exc)) from exc


def cancel_video_schedule(
    db: Session,
    destination_id: str,
    youtube_video_id: str,
) -> dict:
    """Cancel schedule: keep video private, clear publishAt.

    Safe behavior: videos.update with privacyStatus=private and NO publishAt.
    YouTube treats omission as clearing the scheduled publish (video stays
    private). Never deletes the video. Callers must preserve other status
    fields by only sending status part.
    """
    from app.youtube_scheduling import normalize_youtube_error

    youtube = _youtube_client_for_destination(db, destination_id)
    body = {"id": youtube_video_id, "status": {"privacyStatus": "private"}}
    try:
        return (
            youtube.videos()
            .update(part="status", body=body)
            .execute()
        )
    except HttpError as exc:
        raise RuntimeError(normalize_youtube_error(exc)) from exc


def get_video_status(
    db: Session,
    destination_id: str,
    youtube_video_id: str,
) -> dict:
    """Read privacyStatus / publishedAt / scheduled publishAt via videos.list."""
    from app.youtube_scheduling import normalize_youtube_error

    youtube = _youtube_client_for_destination(db, destination_id)
    try:
        resp = (
            youtube.videos()
            .list(part="status,snippet", id=youtube_video_id)
            .execute()
        )
    except HttpError as exc:
        raise RuntimeError(normalize_youtube_error(exc)) from exc
    items = (resp or {}).get("items", [])
    if not items:
        raise RuntimeError(f"YouTube video not found: {youtube_video_id}")
    item = items[0]
    status = item.get("status", {}) or {}
    snippet = item.get("snippet", {}) or {}
    return {
        "video_id": youtube_video_id,
        "privacyStatus": status.get("privacyStatus"),
        "publishAt": status.get("publishAt"),
        "uploadStatus": status.get("uploadStatus"),
        "publishedAt": snippet.get("publishedAt"),
        "raw": item,
    }
