"""YouTube OAuth flow — reusable from backend_facebook, adapted for TikTok."""

import json
import logging
import secrets
import time
from typing import Any

from google_auth_oauthlib.flow import Flow

from ..config import settings
from ..db.repositories import destinations, youtube_auth

logger = logging.getLogger("backend-tiktok.services.youtube_oauth")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtubepartner-reporting",
]


def _client_config() -> dict[str, Any]:
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uris": [settings.tiktok_youtube_callback_url],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


async def build_auth_url(
    destination_id: str, pipeline_id: str, return_to: str | None = None
) -> tuple[str, str]:
    """Return (auth_url, state). Caller redirects user to auth_url."""
    state = secrets.token_hex(32)
    redirect_uri = settings.tiktok_youtube_callback_url
    if not redirect_uri:
        raise RuntimeError("TIKTOK_YOUTUBE_CALLBACK_URL is not configured")

    expires_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 600))
    await youtube_auth.create_oauth_state(
        state, destination_id, pipeline_id, expires_at, return_to
    )

    flow = Flow(
        client_config=_client_config(),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
        state=state,
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    logger.info("YouTube OAuth URL generated for destination %s", destination_id)
    return auth_url, state


async def handle_callback(code: str, state: str) -> dict[str, Any]:
    """Exchange auth code for credentials, store them, mark destination connected."""
    saved = await youtube_auth.consume_oauth_state(state)
    if saved is None:
        raise ValueError("Invalid or expired OAuth state")

    redirect_uri = settings.tiktok_youtube_callback_url
    flow = Flow(
        client_config=_client_config(),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
        state=state,
    )
    flow.fetch_token(code=code)

    creds = flow.credentials
    credentials_json = json.dumps(
        {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes,
        }
    )

    await youtube_auth.save_credentials(saved["destination_id"], credentials_json)
    await destinations.update_destination_connected(
        saved["destination_id"], connected=True, account_id=creds.client_id
    )
    logger.info("YouTube OAuth completed for destination %s", saved["destination_id"])
    return {"destination_id": saved["destination_id"], "pipeline_id": saved["pipeline_id"]}
