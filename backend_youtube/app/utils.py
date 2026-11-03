import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from .db.session import is_sqlite


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gen_id(prefix: str, n: int = 12) -> str:
    return f"{prefix}_{secrets.token_hex(n//2)}"


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


ENCRYPTION_KEY = None
try:
    from cryptography.fernet import Fernet  # type: ignore

    import os
    _env_key = os.getenv("TOKEN_ENCRYPTION_KEY")
    if _env_key:
        ENCRYPTION_KEY = Fernet(_env_key.strip())
except Exception:
    ENCRYPTION_KEY = None


_token_cache: dict[str, str] = {}


def encrypt_token(value: str) -> str:
    if not ENCRYPTION_KEY:
        return f"plain:{value}"
    return "fernet:" + ENCRYPTION_KEY.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_token(value: str) -> str:
    if value.startswith("fernet:"):
        if not ENCRYPTION_KEY:
            raise RuntimeError("TOKEN_ENCRYPTION_KEY is required to decrypt stored tokens")
        return ENCRYPTION_KEY.decrypt(value[len("fernet:"):].encode("utf-8")).decode("utf-8")
    if value.startswith("plain:"):
        return value[len("plain:"):]
    return value


def cache_key(pipeline_id: str, key_type: str) -> str:
    return f"youtube:{pipeline_id}:{key_type}"
