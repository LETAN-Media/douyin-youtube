"""Encryption for saved Douyin login sessions and per-source cookies at rest.

Uses Fernet (AES-128-CBC + HMAC) with a key derived from
``APP_ENCRYPTION_KEY`` (preferred), ``SESSION_ENCRYPTION_KEY``,
or ``ADMIN_TOKEN`` as fallback.
Cookie/session values are never logged anywhere in this codebase.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _fernet() -> Fernet:
    secret = (
        (settings.app_encryption_key or "").strip()
        or (settings.session_encryption_key or "").strip()
        or (settings.admin_token or "").strip()
    )
    if not secret:
        raise RuntimeError(
            "No encryption secret available "
            "(set APP_ENCRYPTION_KEY, SESSION_ENCRYPTION_KEY or ADMIN_TOKEN)"
        )
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_text(raw: str) -> str:
    if not raw or not raw.strip():
        raise ValueError("Empty value")
    return _fernet().encrypt(raw.encode("utf-8")).decode("ascii")


def decrypt_text(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Value cannot be decrypted") from exc


def encrypt_storage_state(raw_json: str) -> str:
    if not raw_json or not raw_json.strip():
        raise ValueError("Empty storage state")
    return encrypt_text(raw_json)


def decrypt_storage_state(token: str) -> str:
    try:
        return decrypt_text(token)
    except ValueError as exc:
        raise ValueError("Douyin session cannot be decrypted") from exc
