import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppSetting, OAuthState


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

TOKEN_SETTING_KEY = "youtube_credentials"


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
                "https://accounts.google.com/o/oauth2/auth"
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
) -> str:
    validate_google_config()

    state = secrets.token_urlsafe(48)

    db.add(
        OAuthState(
            state=state,
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
            prompt="consent",
        )
    )

    return authorization_url


def complete_oauth(
    db: Session,
    state: str,
    authorization_response: str,
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

    old_refresh_token = None

    existing = read_setting(
        db,
        TOKEN_SETTING_KEY,
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

    save_setting(
        db,
        TOKEN_SETTING_KEY,
        json.dumps(data),
    )

    state_row = db.get(
        OAuthState,
        state,
    )

    if state_row:
        db.delete(state_row)
        db.commit()


def load_credentials(
    db: Session,
) -> Credentials:
    raw = read_setting(
        db,
        TOKEN_SETTING_KEY,
    )

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

        save_setting(
            db,
            TOKEN_SETTING_KEY,
            json.dumps(data),
        )

    return credentials


def youtube_connected(
    db: Session,
) -> bool:
    raw = read_setting(
        db,
        TOKEN_SETTING_KEY,
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


def upload_video(
    db: Session,
    file_path: Path,
    title: str,
    description: str,
    privacy_status: str,
) -> str:
    if not file_path.exists():
        raise RuntimeError(
            f"Không tìm thấy video: {file_path}"
        )

    credentials = load_credentials(
        db
    )

    youtube = build(
        "youtube",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )

    body = {
        "snippet": {
            "title": title[:100],
            "description": (
                description[:5000]
            ),
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": (
                privacy_status
            ),
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
                raise RuntimeError(
                    f"YouTube API error "
                    f"{status_code}: {exc}"
                ) from exc

            retry_count += 1

            if retry_count > max_retries:
                raise RuntimeError(
                    "YouTube upload thất bại "
                    "sau nhiều lần retry"
                ) from exc

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
