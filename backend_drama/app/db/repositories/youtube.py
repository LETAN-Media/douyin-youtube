"""YouTube destinations + encrypted OAuth credentials (drama).

Refresh tokens are Fernet-encrypted with DRAMA_TOKEN_ENCRYPTION_KEY and
never leave this module decrypted except in-memory to the uploader.
Nothing here logs secrets.
"""

import uuid
from typing import Any

from ..client import get_client


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fernet():
    from cryptography.fernet import Fernet, InvalidToken  # noqa: F401

    from ...config import settings

    key = (settings.DRAMA_TOKEN_ENCRYPTION_KEY or "").strip()
    if not key:
        raise RuntimeError(
            "DRAMA_TOKEN_ENCRYPTION_KEY is not configured; refusing to handle credentials."
        )
    return Fernet(key.encode())


def encrypt_refresh_token(refresh_token: str) -> str:
    return _fernet().encrypt(refresh_token.encode()).decode()


def decrypt_refresh_token(blob: str) -> str:
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(blob.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Stored YouTube credentials cannot be decrypted.") from exc


def _row_to_destination(r: Any) -> dict[str, Any]:
    get = r.get if hasattr(r, "get") else None

    def _col(name: str, idx: int, default: Any = None):
        if get is not None:
            try:
                v = r[name]
                return v if v is not None else default
            except Exception:
                pass
        try:
            v = r[idx]
            return v if v is not None else default
        except Exception:
            return default

    return {
        "id": _col("id", 0),
        "pipeline_id": _col("pipeline_id", 1),
        "channel_id": _col("channel_id", 2),
        "channel_title": _col("channel_title", 3),
        "channel_thumbnail": _col("channel_thumbnail", 4),
        "visibility": _col("visibility", 5) or "public",
        "enabled": bool(_col("enabled", 6, 1)),
        "connected": bool(_col("connected", 7, 0)),
        "connected_at": _col("connected_at", 8),
    }


_DEST_COLUMNS = (
    "id, pipeline_id, channel_id, channel_title, channel_thumbnail, "
    "visibility, enabled, connected, connected_at"
)


def create_destination(*, pipeline_id: str, visibility: str = "public",
                       enabled: bool = True) -> dict[str, Any]:
    conn = get_client()
    did = f"dytd_{uuid.uuid4().hex[:12]}"
    conn.execute(
        "INSERT INTO drama_youtube_destinations (id, pipeline_id, visibility, enabled) "
        "VALUES (?, ?, ?, ?)",
        (did, pipeline_id, visibility, 1 if enabled else 0),
    )
    conn.commit()
    row = get_destination(did)
    assert row is not None
    return row


def get_destination(destination_id: str) -> dict[str, Any] | None:
    conn = get_client()
    row = conn.execute(
        f"SELECT {_DEST_COLUMNS} FROM drama_youtube_destinations WHERE id = ?",
        (destination_id,),
    ).fetchone()
    return _row_to_destination(row) if row is not None else None


def list_destinations(pipeline_id: str | None = None) -> list[dict[str, Any]]:
    conn = get_client()
    if pipeline_id:
        rows = conn.execute(
            f"SELECT {_DEST_COLUMNS} FROM drama_youtube_destinations "
            "WHERE pipeline_id = ? ORDER BY created_at ASC, id ASC",
            (pipeline_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {_DEST_COLUMNS} FROM drama_youtube_destinations "
            "WHERE connected = 1 ORDER BY updated_at DESC, id ASC LIMIT 100",
        ).fetchall()
    return [_row_to_destination(r) for r in rows]


def set_connected(destination_id: str, *, channel_id: str, channel_title: str | None,
                  channel_thumbnail: str | None = None) -> dict[str, Any] | None:
    conn = get_client()
    conn.execute(
        "UPDATE drama_youtube_destinations SET channel_id = ?, channel_title = ?, "
        "channel_thumbnail = ?, connected = 1, connected_at = ?, updated_at = ? "
        "WHERE id = ?",
        (channel_id, channel_title, channel_thumbnail, _now(), _now(), destination_id),
    )
    conn.commit()
    return get_destination(destination_id)


def disconnect_destination(destination_id: str) -> dict[str, Any] | None:
    conn = get_client()
    if get_destination(destination_id) is None:
        return None
    conn.execute("DELETE FROM drama_youtube_credentials WHERE destination_id = ?", (destination_id,))
    conn.execute("DELETE FROM drama_oauth_states WHERE destination_id = ?", (destination_id,))
    conn.execute(
        "UPDATE drama_youtube_destinations SET connected = 0, enabled = 0, updated_at = ? "
        "WHERE id = ?",
        (_now(), destination_id),
    )
    conn.commit()
    return get_destination(destination_id)


def save_credentials(destination_id: str, *, channel_id: str,
                      refresh_token: str | None) -> None:
    """Persist (encrypted). A missing new refresh token never wipes the old one."""
    conn = get_client()
    existing = conn.execute(
        "SELECT refresh_token_encrypted FROM drama_youtube_credentials WHERE destination_id = ?",
        (destination_id,),
    ).fetchone()

    def _enc(row: Any) -> str | None:
        try:
            return row["refresh_token_encrypted"]
        except Exception:
            pass
        try:
            return row[0]
        except Exception:
            return None

    blob = encrypt_refresh_token(refresh_token) if refresh_token else None
    if blob is None:
        blob = _enc(existing) if existing is not None else None
    if blob is None:
        raise RuntimeError("No refresh token available to store.")
    conn.execute(
        "INSERT INTO drama_youtube_credentials (destination_id, channel_id, "
        "refresh_token_encrypted, status, connected_at, updated_at) "
        "VALUES (?, ?, ?, 'active', ?, ?) "
        "ON CONFLICT(destination_id) DO UPDATE SET channel_id = excluded.channel_id, "
        "refresh_token_encrypted = excluded.refresh_token_encrypted, "
        "status = 'active', connected_at = excluded.connected_at, "
        "updated_at = excluded.updated_at",
        (destination_id, channel_id, blob, _now(), _now()),
    )
    conn.commit()


def load_refresh_token(destination_id: str) -> str:
    conn = get_client()
    row = conn.execute(
        "SELECT refresh_token_encrypted FROM drama_youtube_credentials WHERE destination_id = ?",
        (destination_id,),
    ).fetchone()
    blob = None
    if row is not None:
        try:
            blob = row["refresh_token_encrypted"]
        except Exception:
            try:
                blob = row[0]
            except Exception:
                blob = None
    if not blob:
        raise RuntimeError("No stored credentials for this destination.")
    return decrypt_refresh_token(blob)


def credentials_present(destination_id: str) -> bool:
    try:
        token = load_refresh_token(destination_id)
        return bool(token)
    except Exception:
        return False


def create_oauth_state(*, state: str, destination_id: str, pipeline_id: str,
                       return_to: str | None, expires_at: str) -> None:
    conn = get_client()
    conn.execute(
        "INSERT INTO drama_oauth_states (state, destination_id, pipeline_id, "
        "return_to, expires_at) VALUES (?, ?, ?, ?, ?)",
        (state, destination_id, pipeline_id, return_to, expires_at),
    )
    conn.commit()


def get_oauth_state(state: str) -> dict[str, Any] | None:
    conn = get_client()
    row = conn.execute(
        "SELECT state, destination_id, pipeline_id, return_to, expires_at "
        "FROM drama_oauth_states WHERE state = ?",
        (state,),
    ).fetchone()
    if row is None:
        return None

    def _col(name: str, idx: int):
        try:
            return row[name]
        except Exception:
            pass
        try:
            return row[idx]
        except Exception:
            return None

    return {
        "state": _col("state", 0),
        "destination_id": _col("destination_id", 1),
        "pipeline_id": _col("pipeline_id", 2),
        "return_to": _col("return_to", 3),
        "expires_at": _col("expires_at", 4),
    }


def delete_oauth_state(state: str) -> None:
    conn = get_client()
    conn.execute("DELETE FROM drama_oauth_states WHERE state = ?", (state,))
    conn.commit()
