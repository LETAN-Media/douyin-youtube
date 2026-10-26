"""YouTube destination OAuth for TikTok pipelines.

Per-destination credentials, server-side one-time state, offline access,
refresh-token preservation, channel binding verified via YouTube Data API v3 channels.list.
No token ever leaves through logs, errors, or API responses.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import secrets
from typing import Any, Callable

from google_auth_oauthlib.flow import Flow

from ..config import settings
from ..db.repositories import destinations as destinations_repo
from ..db.repositories import youtube_auth as auth_repo

logger = logging.getLogger("backend-tiktok.services.youtube_oauth")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

STATE_TTL_MINUTES = 10


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_google_config() -> tuple[str, str, str]:
    client_id = (settings.google_client_id or "").strip()
    client_secret = (settings.google_client_secret or "").strip()
    callback_url = (settings.tiktok_youtube_callback_url or "").strip()
    missing = []
    if not client_id:
        missing.append("GOOGLE_CLIENT_ID")
    if not client_secret:
        missing.append("GOOGLE_CLIENT_SECRET")
    if not callback_url:
        missing.append("TIKTOK_YOUTUBE_CALLBACK_URL")
    if missing:
        raise RuntimeError(f"Missing Google OAuth config: {', '.join(missing)}")
    return client_id, client_secret, callback_url


def build_client_config() -> dict[str, Any]:
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


def _new_flow(state: str):
    _, _, callback_url = validate_google_config()
    flow = Flow.from_client_config(
        build_client_config(),
        scopes=SCOPES,
        state=state,
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = callback_url
    return flow


def _fetch_channel(flow: Any) -> tuple[str, str, str | None]:
    from googleapiclient.discovery import build

    youtube = build("youtube", "v3", credentials=flow.credentials, cache_discovery=False)
    result = youtube.channels().list(part="id,snippet", mine=True).execute()
    items = (result or {}).get("items", [])
    if not items:
        raise RuntimeError("No YouTube channel found on this Google account")
    channel = items[0]
    channel_id = channel["id"]
    snippet = channel.get("snippet", {})
    channel_name = snippet.get("title") or "YouTube Channel"
    thumbnails = snippet.get("thumbnails", {})
    avatar_url = (
        thumbnails.get("default", {}).get("url")
        or thumbnails.get("medium", {}).get("url")
        or thumbnails.get("high", {}).get("url")
    )
    return channel_id, channel_name, avatar_url


def sanitize_return_to(value: str | None) -> str | None:
    """Whitelist an OAuth return path. Only in-dashboard /tiktok/* paths."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not v.startswith("/tiktok"):
        return None
    if v.startswith("//") or "\\" in v or "://" in v:
        return None
    if len(v) > 200:
        return None
    return v


async def build_auth_url(
    destination_id: str, pipeline_id: str, return_to: str | None = None
) -> tuple[str, str]:
    destination = await destinations_repo.get_destination(destination_id)
    if destination is None:
        raise RuntimeError("Destination does not exist")
    if destination.get("pipeline_id") != pipeline_id:
        raise RuntimeError("Destination does not belong to this pipeline")

    _, _, callback_url = validate_google_config()
    state = secrets.token_urlsafe(48)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=STATE_TTL_MINUTES)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    sanitized_return = sanitize_return_to(return_to)
    await auth_repo.create_oauth_state(
        state=state,
        destination_id=destination_id,
        pipeline_id=pipeline_id,
        expires_at=expires_at,
        return_to=sanitized_return,
    )

    flow = Flow.from_client_config(
        build_client_config(),
        scopes=SCOPES,
        state=state,
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = callback_url
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent select_account",
    )
    logger.info("YouTube OAuth URL generated for destination %s", destination_id)
    return auth_url, state


async def handle_callback(
    code: str,
    state: str,
    *,
    flow_factory: Callable[..., Any] | None = None,
    channel_fetcher: Callable[[Any], tuple[str, str, str | None]] | None = None,
) -> dict[str, Any]:
    if not code or not code.strip():
        raise RuntimeError("OAuth code is missing")
    if not state or not state.strip():
        raise RuntimeError("OAuth state is missing")

    saved = await auth_repo.consume_oauth_state(state.strip())
    if saved is None:
        raise RuntimeError("OAuth state does not exist or has already been used")

    try:
        expires_at = datetime.strptime(saved["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except (ValueError, TypeError):
        expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    if expires_at < datetime.now(timezone.utc):
        raise RuntimeError("OAuth state has expired")

    destination = await destinations_repo.get_destination(saved["destination_id"])
    if destination is None:
        raise RuntimeError("Destination does not exist")
    if destination.get("pipeline_id") != saved["pipeline_id"]:
        raise RuntimeError("OAuth state destination mismatch")

    old_refresh_token: str | None = None
    existing = await auth_repo.get_credentials(destination["id"])
    if existing:
        try:
            old_refresh_token = json.loads(existing["credentials_json"]).get("refresh_token")
        except Exception:
            old_refresh_token = None

    factory = flow_factory or _new_flow
    flow = factory(state)
    _, _, callback_url = validate_google_config()
    flow.redirect_uri = callback_url

    try:
        await asyncio.to_thread(flow.fetch_token, code=code.strip())
    except Exception as exc:
        logger.warning("Token exchange failed for destination %s: %s", destination["id"], exc)
        raise RuntimeError(f"GOOGLE_TOKEN_EXCHANGE_FAILED: {exc}") from exc

    credentials = flow.credentials
    refresh_token = getattr(credentials, "refresh_token", None) or old_refresh_token

    data = {
        "token": getattr(credentials, "token", None),
        "refresh_token": refresh_token,
        "token_uri": getattr(credentials, "token_uri", None),
        "client_id": getattr(credentials, "client_id", None),
        "client_secret": getattr(credentials, "client_secret", None),
        "scopes": getattr(credentials, "scopes", SCOPES),
    }

    fetcher = channel_fetcher or _fetch_channel
    try:
        channel_id, channel_name, channel_avatar_url = await asyncio.to_thread(fetcher, flow)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"YouTube channel lookup failed: {exc}") from exc

    await auth_repo.save_credentials(destination["id"], json.dumps(data))
    await destinations_repo.set_destination_connected(
        destination_id=destination["id"],
        channel_id=channel_id,
        channel_name=channel_name,
        channel_avatar_url=channel_avatar_url,
        account_id=getattr(credentials, "client_id", None),
    )
    logger.info(
        "YouTube OAuth completed for destination %s (channel: %s / %s)",
        destination["id"],
        channel_id,
        channel_name,
    )
    return {
        "ok": True,
        "destination_id": destination["id"],
        "pipeline_id": destination["pipeline_id"],
        "channel_id": channel_id,
        "channel_name": channel_name,
        "channel_avatar_url": channel_avatar_url,
        "return_to": sanitize_return_to(saved.get("return_to")),
    }
