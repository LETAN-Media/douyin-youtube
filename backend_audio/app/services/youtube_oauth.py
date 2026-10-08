"""YouTube OAuth for Audio pipelines: dedicated callback, own Fernet key/store.

Callback: /api/audio/youtube/oauth/callback (NOT shared with drama).
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import Any
from urllib.parse import urlencode

logger = logging.getLogger("backend-audio.oauth")

STATE_TTL_SECONDS = 600
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube"]


class OAuthError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise OAuthError("CRYPTO_MISSING", "cryptography is not installed.")
    from app.config import settings

    key = (settings.AUDIO_TOKEN_ENCRYPTION_KEY or "").strip()
    if not key:
        raise OAuthError("ENCRYPTION_KEY_MISSING",
                         "AUDIO_TOKEN_ENCRYPTION_KEY is not configured.")
    return Fernet(key.encode())


def encrypt_refresh_token(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def decrypt_refresh_token(blob: str) -> str:
    return _fernet().decrypt(blob.encode()).decode()


def oauth_configured() -> bool:
    from app.config import settings

    return bool((settings.GOOGLE_CLIENT_ID or "").strip()
                and (settings.GOOGLE_CLIENT_SECRET or "").strip()
                and (settings.AUDIO_YOUTUBE_CALLBACK_URL or "").strip())


def start_oauth(pipeline_id: str, destination_id: str,
                return_to: str | None = None) -> dict[str, str]:
    from app.config import settings
    from app.db.client import get_client

    if not oauth_configured():
        raise OAuthError("OAUTH_NOT_CONFIGURED", "Google OAuth is not configured.")
    state = secrets.token_urlsafe(32)
    client = get_client()
    client.execute(
        "INSERT INTO audio_oauth_states (state, destination_id, pipeline_id, "
        "return_to, expires_at) VALUES (?, ?, ?, ?, ?)",
        (state, destination_id,
         pipeline_id, return_to,
         time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + STATE_TTL_SECONDS))))
    client.commit()
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.AUDIO_YOUTUBE_CALLBACK_URL,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return {"authorization_url": f"{GOOGLE_AUTH_URL}?{urlencode(params)}",
            "destination_id": destination_id}


def consume_state(state: str) -> dict[str, Any]:
    from app.db.client import get_client

    client = get_client()
    row = client.execute("SELECT * FROM audio_oauth_states WHERE state = ?",
                         (state,)).fetchone()
    if row is None:
        raise OAuthError("INVALID_STATE", "Unknown OAuth state.")
    client.execute("DELETE FROM audio_oauth_states WHERE state = ?", (state,))
    client.commit()
    return dict(row)


async def exchange_code(code: str) -> dict[str, Any]:
    import httpx

    from app.config import settings

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(GOOGLE_TOKEN_URL, data={
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.AUDIO_YOUTUBE_CALLBACK_URL,
            "grant_type": "authorization_code",
            "code": code,
        })
    if resp.status_code != 200:
        raise OAuthError("TOKEN_EXCHANGE_FAILED",
                         f"Google HTTP {resp.status_code}.")
    return resp.json()


async def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    import httpx

    from app.config import settings

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(GOOGLE_TOKEN_URL, data={
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        })
    if resp.status_code != 200:
        raise OAuthError("REFRESH_FAILED", f"Google HTTP {resp.status_code}.")
    return resp.json()


def save_credentials(destination_id: str, channel_id: str | None,
                      refresh_token: str) -> None:
    from app.db.client import get_client
    from app.db.repositories import now_iso

    client = get_client()
    blob = encrypt_refresh_token(refresh_token)
    client.execute(
        "INSERT INTO audio_youtube_credentials (destination_id, channel_id, "
        "refresh_token_encrypted, status, connected_at, updated_at) "
        "VALUES (?, ?, ?, 'active', ?, ?) "
        "ON CONFLICT(destination_id) DO UPDATE SET channel_id=excluded.channel_id, "
        "refresh_token_encrypted=excluded.refresh_token_encrypted, status='active', "
        "connected_at=excluded.connected_at, updated_at=excluded.updated_at",
        (destination_id, channel_id, blob, now_iso(), now_iso()))
    client.execute(
        "UPDATE audio_destinations SET connected = 1, channel_id = COALESCE(?, channel_id), "
        "connected_at = ?, updated_at = ? WHERE id = ?",
        (channel_id, now_iso(), now_iso(), destination_id))
    client.commit()


def load_credentials(destination_id: str) -> dict[str, Any]:
    from app.db.client import get_client

    row = get_client().execute(
        "SELECT * FROM audio_youtube_credentials WHERE destination_id = ?",
        (destination_id,)).fetchone()
    if row is None or row["status"] != "active" or not row["refresh_token_encrypted"]:
        raise OAuthError("NOT_CONNECTED", "Destination is not connected.")
    return {"refresh_token": decrypt_refresh_token(row["refresh_token_encrypted"]),
            "channel_id": row["channel_id"]}


def disconnect(destination_id: str) -> None:
    from app.db.client import get_client
    from app.db.repositories import now_iso

    client = get_client()
    client.execute(
        "UPDATE audio_youtube_credentials SET status = 'revoked', updated_at = ? "
        "WHERE destination_id = ?", (now_iso(), destination_id))
    client.execute(
        "UPDATE audio_destinations SET connected = 0, updated_at = ? WHERE id = ?",
        (now_iso(), destination_id))
    client.commit()
