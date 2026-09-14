"""Encryption for saved Douyin login sessions at rest.

Uses Fernet (AES-128-CBC + HMAC) with a key derived from
``SESSION_ENCRYPTION_KEY`` (or ``ADMIN_TOKEN`` as fallback).
Cookie/session values are never logged anywhere in this codebase.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _fernet() -> Fernet:
    secret = (
        (settings.session_encryption_key or "").strip()
        or (settings.admin_token or "").strip()
    )
    if not secret:
        raise RuntimeError(
            "No encryption secret available "
            "(set SESSION_ENCRYPTION_KEY or ADMIN_TOKEN)"
        )
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_storage_state(raw_json: str) -> str:
    if not raw_json or not raw_json.strip():
        raise ValueError("Empty storage state")
    return _fernet().encrypt(raw_json.encode("utf-8")).decode("ascii")


def decrypt_storage_state(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Douyin session cannot be decrypted") from exc
