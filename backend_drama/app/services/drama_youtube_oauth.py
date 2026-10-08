"""YouTube OAuth for drama pipelines (authorization-code flow).

Modeled on the proven backend_facebook implementation, scoped to drama
tables. Tokens never leave the backend; only ids/titles/thumbnails do.

- state: random, 15-minute TTL, single-use (deleted on completion).
- redirect_uri always comes from DRAMA_YOUTUBE_CALLBACK_URL (never from
  user input); must match Google Cloud Console exactly.
- return_to is whitelisted to in-dashboard /drama/* paths only.
- A missing new refresh token never wipes the stored one.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone

from ..db.repositories import youtube as yt_repo

logger = logging.getLogger("backend-drama-youtube-oauth")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

STATE_TTL_MINUTES = 15


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_google_config() -> tuple[str, str, str]:
    """Fail fast from existing env. Never logs secrets."""
    from ..config import settings

    client_id = (settings.GOOGLE_CLIENT_ID or "").strip()
    client_secret = (settings.GOOGLE_CLIENT_SECRET or "").strip()
    callback_url = (settings.DRAMA_YOUTUBE_CALLBACK_URL or "").strip()
    missing = []
    if not client_id:
        missing.append("GOOGLE_CLIENT_ID")
    if not client_secret:
        missing.append("GOOGLE_CLIENT_SECRET")
    if not callback_url:
        missing.append("DRAMA_YOUTUBE_CALLBACK_URL")
    if missing:
        raise RuntimeError(f"Missing Google OAuth config: {', '.join(missing)}")
    return client_id, client_secret, callback_url


def build_client_config() -> dict:
    client_id, client_secret, callback_url = validate_google_config()
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [callback_url],
        }
    }


def sanitize_return_to(value: str | None) -> str | None:
    """Whitelist an OAuth return path: in-dashboard /drama/* paths only."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not v.startswith("/drama/"):
        return None
    if v.startswith("//") or "\\" in v or "://" in v:
        return None
    if len(v) > 200:
        return None
    return v


def _new_flow(state: str):
    from google_auth_oauthlib.flow import Flow

    _, _, callback_url = validate_google_config()
    flow = Flow.from_client_config(
        build_client_config(), scopes=SCOPES, state=state,
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = callback_url
    return flow


def _fetch_channel(flow) -> tuple[str, str, str | None]:
    from googleapiclient.discovery import build

    youtube = build("youtube", "v3", credentials=flow.credentials, cache_discovery=False)
    result = youtube.channels().list(part="id,snippet", mine=True).execute()
    items = (result or {}).get("items", [])
    if not items:
        raise RuntimeError("No YouTube channel found on this Google account")
    channel = items[0]
    snippet = channel.get("snippet") or {}
    thumbnails = snippet.get("thumbnails") or {}
    thumb = None
    for size in ("default", "medium", "high"):
        url = (thumbnails.get(size) or {}).get("url")
        if url:
            thumb = url
            break
    return channel["id"], snippet.get("title") or "", thumb


async def create_authorization_url(
    pipeline_id: str, visibility: str = "public", return_to: str | None = None
) -> tuple[str, str]:
    """Create a placeholder destination + state, return (auth_url, destination_id)."""
    from ..db.repositories import drama as drama_repo

    if drama_repo.get_pipeline(pipeline_id) is None:
        raise RuntimeError("Pipeline not found")
    validate_google_config()
    destination = yt_repo.create_destination(
        pipeline_id=pipeline_id, visibility=visibility or "public"
    )
    state = secrets.token_urlsafe(48)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=STATE_TTL_MINUTES)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    yt_repo.create_oauth_state(
        state=state, destination_id=destination["id"],
        pipeline_id=pipeline_id, expires_at=expires_at,
        return_to=sanitize_return_to(return_to),
    )
    flow = _new_flow(state)
    auth_url, _ = flow.authorization_url(
        access_type="offline", prompt="consent", include_granted_scopes="true"
    )
    return auth_url, destination["id"]


async def complete_oauth(state: str, code: str) -> dict:
    """Exchange code, verify channel binding, persist credentials.

    Single-use state (deleted after read). Returns public info only.
    """
    stored = yt_repo.get_oauth_state(state)
    if stored is None:
        raise RuntimeError("OAuth state does not exist or was already used")
    if not stored.get("expires_at") or stored["expires_at"] < utcnow_iso():
        yt_repo.delete_oauth_state(state)
        raise RuntimeError("OAuth state expired")
    destination = yt_repo.get_destination(stored["destination_id"])
    if destination is None or destination.get("pipeline_id") != stored.get("pipeline_id"):
        yt_repo.delete_oauth_state(state)
        raise RuntimeError("OAuth state does not match any destination")

    old_refresh_token: str | None = None
    try:
        old_refresh_token = yt_repo.load_refresh_token(destination["id"])
    except Exception:
        old_refresh_token = None

    flow = _new_flow(state)
    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        yt_repo.delete_oauth_state(state)
        raise RuntimeError(f"Google token exchange failed: {type(exc).__name__}")
    try:
        channel_id, channel_title, channel_thumbnail = _fetch_channel(flow)
    except Exception as exc:
        yt_repo.delete_oauth_state(state)
        raise RuntimeError(f"Could not read YouTube channel: {type(exc).__name__}")

    refresh_token = getattr(flow.credentials, "refresh_token", None) or old_refresh_token
    yt_repo.delete_oauth_state(state)
    if not refresh_token:
        raise RuntimeError("Google did not return a refresh token and none is stored")
    yt_repo.save_credentials(
        destination["id"], channel_id=channel_id, refresh_token=refresh_token
    )
    updated = yt_repo.set_connected(
        destination["id"], channel_id=channel_id, channel_title=channel_title,
        channel_thumbnail=channel_thumbnail,
    )
    return {
        "destination_id": destination["id"],
        "pipeline_id": destination["pipeline_id"],
        "channel_id": channel_id,
        "channel_title": channel_title,
        "channel_thumbnail": channel_thumbnail,
        "connected": bool(updated and updated.get("connected")),
        "return_to": sanitize_return_to(stored.get("return_to")),
    }


async def load_credentials(destination_id: str):
    """Build google Credentials with auto-refresh for the uploader."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    from ..config import settings

    destination = yt_repo.get_destination(destination_id)
    if destination is None or not destination.get("connected"):
        raise RuntimeError("Destination is not connected")
    client_id = (settings.GOOGLE_CLIENT_ID or "").strip()
    client_secret = (settings.GOOGLE_CLIENT_SECRET or "").strip()
    refresh_token = yt_repo.load_refresh_token(destination_id)
    creds = Credentials(
        token=None, refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id, client_secret=client_secret,
        scopes=SCOPES,
    )
    if not creds.valid:
        creds.refresh(Request())
        fresh = getattr(creds, "refresh_token", None)
        if fresh and fresh != refresh_token:
            yt_repo.save_credentials(
                destination_id, channel_id=destination.get("channel_id") or "",
                refresh_token=fresh,
            )
    return creds
