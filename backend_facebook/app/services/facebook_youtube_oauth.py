"""YouTube destination OAuth for Facebook pipelines (Task 7A).

Port of the proven backend/app/youtube.py pattern onto Turso/libsql:
per-destination credentials, server-side one-time state, offline access,
own-refresh-token preservation, channel binding verified via channels.list.
No token ever leaves through logs, errors, or API responses.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ..config import settings
from ..db.repositories import destinations as destinations_repo
from ..db.repositories import youtube_auth as auth_repo

logger = logging.getLogger("backend-facebook.youtube-oauth")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

STATE_TTL_MINUTES = 15


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _redact_oauth_error(exc: Exception) -> str:
    """Keep the OAuth2 error code/description, strip anything secret-looking."""
    text = f"{type(exc).__name__}: {exc}"
    for secret in (
        settings.GOOGLE_CLIENT_SECRET,
        settings.GOOGLE_CLIENT_ID,
        settings.ADMIN_TOKEN,
    ):
        if secret and len(secret) > 4 and secret in text:
            text = text.replace(secret, "***")
    # client_id prefix (project number) is a public identifier; keep error short
    return text[:300]


def provider_error_code(exc: Exception) -> str:
    """Stable provider error code from an OAuth2/token failure. No secrets."""
    raw = getattr(exc, "error", None)
    if isinstance(raw, str) and raw.strip():
        code = "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in raw.strip().lower())
        return code[:64] or "unknown"
    name = type(exc).__name__
    mapping = {
        "InvalidClientError": "invalid_client",
        "InvalidGrantError": "invalid_grant",
        "InvalidScopeError": "invalid_scope",
        "UnauthorizedClientError": "unauthorized_client",
        "UnsupportedGrantTypeError": "unsupported_grant_type",
        "InvalidRequestError": "invalid_request",
        "MismatchingStateError": "mismatching_state",
        "MissingCodeError": "missing_code",
        "MissingTokenError": "missing_token",
        "ConnectionError": "connection_error",
        "ConnectTimeout": "connection_error",
        "Timeout": "timeout",
        "ReadTimeout": "timeout",
    }
    if name in mapping:
        return mapping[name]
    lowered = name.lower()
    if "timeout" in lowered:
        return "timeout"
    if "connect" in lowered or "network" in lowered:
        return "connection_error"
    return "unknown"


def verify_granted_scopes(granted: Any) -> list[str]:
    """Accept a superset; reject when a REQUIRED scope is missing. Scope names are public."""
    if granted is None:
        return list(SCOPES)
    if isinstance(granted, str):
        granted_list = granted.split()
    else:
        try:
            granted_list = list(granted)
        except TypeError:
            return list(SCOPES)
    missing = [s for s in SCOPES if s not in granted_list]
    if missing:
        raise RuntimeError(
            "Granted scopes missing required scopes: " + ", ".join(missing)
        )
    return granted_list


def validate_google_config() -> tuple[str, str, str]:
    """Fail fast from existing env. Never logs secrets."""
    client_id = (settings.GOOGLE_CLIENT_ID or "").strip()
    client_secret = (settings.GOOGLE_CLIENT_SECRET or "").strip()
    callback_url = (settings.FACEBOOK_YOUTUBE_CALLBACK_URL or "").strip()
    missing = []
    if not client_id:
        missing.append("GOOGLE_CLIENT_ID")
    if not client_secret:
        missing.append("GOOGLE_CLIENT_SECRET")
    if not callback_url:
        missing.append("FACEBOOK_YOUTUBE_CALLBACK_URL")
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
    from google_auth_oauthlib.flow import Flow

    _, _, callback_url = validate_google_config()
    flow = Flow.from_client_config(
        build_client_config(), scopes=SCOPES, state=state,
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = callback_url
    return flow


def _fetch_channel(flow: Any) -> tuple[str, str]:
    from googleapiclient.discovery import build

    youtube = build("youtube", "v3", credentials=flow.credentials, cache_discovery=False)
    result = youtube.channels().list(part="id,snippet", mine=True).execute()
    items = (result or {}).get("items", [])
    if not items:
        raise RuntimeError("No YouTube channel found on this Google account")
    channel = items[0]
    return channel["id"], channel["snippet"]["title"]


async def create_authorization_url(destination_id: str, pipeline_id: str) -> str:
    """Create one-time state and return the Google consent URL."""
    destination = await destinations_repo.get_destination(destination_id)
    if destination is None or destination.get("pipeline_id") != pipeline_id:
        raise RuntimeError("Destination does not belong to this pipeline")
    _, _, callback_url = validate_google_config()

    state = secrets.token_urlsafe(48)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=STATE_TTL_MINUTES)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    await auth_repo.create_oauth_state(
        state=state, destination_id=destination_id,
        pipeline_id=pipeline_id, expires_at=expires_at,
    )

    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        build_client_config(), scopes=SCOPES, state=state,
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = callback_url
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent select_account",
    )
    return authorization_url


async def complete_oauth(
    state: str,
    code: str,
    *,
    flow_factory: Callable[..., Any] | None = None,
    channel_fetcher: Callable[[Any], tuple[str, str]] | None = None,
) -> dict[str, str]:
    """Exchange code, verify channel, bind credentials to the state destination.

    The authorization `code` is passed directly (never a reconstructed proxy
    URL) and `redirect_uri` always comes from FACEBOOK_YOUTUBE_CALLBACK_URL.

    Returns public info only (ids + channel). Old refresh token of THIS
    destination is preserved when Google omits a new one. Never falls back
    to another destination, pipeline, or global token.
    """
    if not code or not code.strip():
        raise RuntimeError("OAuth code is missing")
    stored = await auth_repo.get_oauth_state(state)
    if stored is None:
        raise RuntimeError("OAuth state does not exist")
    try:
        expires_at = datetime.strptime(stored["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except (ValueError, TypeError):
        expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    if expires_at < datetime.now(timezone.utc):
        await auth_repo.delete_oauth_state(state)
        raise RuntimeError("OAuth state has expired")

    destination = await destinations_repo.get_destination(stored["destination_id"])
    if destination is None:
        raise RuntimeError("Destination does not exist")
    if destination.get("pipeline_id") != stored["pipeline_id"]:
        raise RuntimeError("OAuth state does not match this destination")

    old_refresh_token: str | None = None
    existing = await auth_repo.get_credentials(destination["id"])
    if existing:
        try:
            old_refresh_token = json.loads(existing).get("refresh_token")
        except Exception:
            old_refresh_token = None

    factory = flow_factory or _new_flow
    flow = factory(state)
    _, _, callback_url = validate_google_config()
    # redirect_uri is ALWAYS the env-fixed callback URL, never derived from
    # the reverse-proxy request URL (scheme/host may differ behind proxies).
    flow.redirect_uri = callback_url
    try:
        await asyncio.to_thread(flow.fetch_token, code=code.strip())
    except Exception as exc:
        # SAFE diagnostics: OAuth2 error code only (invalid_client,
        # invalid_grant, redirect_uri_mismatch, ...). No code, no secrets,
        # no tokens, no raw callback query, no credentials JSON.
        provider_error = provider_error_code(exc)
        logger.warning("token exchange failed provider_error=%s", provider_error)
        raise RuntimeError(
            f"GOOGLE_TOKEN_EXCHANGE_FAILED provider_error={provider_error}"
        ) from exc
    credentials = flow.credentials

    # Scope expansion: extras from previously-granted scopes are accepted;
    # missing REQUIRED scopes are rejected. Never disabled blindly.
    granted_scopes = verify_granted_scopes(getattr(credentials, "scopes", None))

    refresh_token = getattr(credentials, "refresh_token", None) or old_refresh_token
    data = {
        "token": getattr(credentials, "token", None),
        "refresh_token": refresh_token,
        "token_uri": getattr(credentials, "token_uri", None),
        "client_id": getattr(credentials, "client_id", None),
        "client_secret": getattr(credentials, "client_secret", None),
        "scopes": granted_scopes,
    }

    fetcher = channel_fetcher or _fetch_channel
    try:
        channel_id, channel_name = await asyncio.to_thread(fetcher, flow)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("YouTube channel lookup failed") from exc

    # Bind strictly to the state destination. No cross-destination fallback.
    await auth_repo.save_credentials(destination["id"], json.dumps(data))
    await destinations_repo.set_connected(
        destination["id"], channel_id=channel_id, channel_name=channel_name
    )
    await auth_repo.delete_oauth_state(state)
    logger.info("Saved YouTube OAuth for destination=%s", destination["id"])
    return {
        "destination_id": destination["id"],
        "pipeline_id": destination["pipeline_id"],
        "channel_id": channel_id,
        "channel_name": channel_name,
    }
