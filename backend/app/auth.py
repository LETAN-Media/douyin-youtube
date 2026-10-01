"""Multi-user authentication primitives.

- Passwords: Argon2id (argon2-cffi). Only the hash is ever stored.
- Sessions: opaque 256-bit tokens; only SHA-256(token) is stored in DB.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy.orm import Session

from app.models import User, UserSession, utcnow

_ph = PasswordHasher()  # Argon2id by default

SESSION_TOKEN_BYTES = 32


def hash_password(plaintext: str) -> str:
    if not plaintext or len(plaintext) < 8:
        raise ValueError("Mật khẩu phải có ít nhất 8 ký tự")
    return _ph.hash(plaintext)


def verify_password(plaintext: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, plaintext)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def new_session_token() -> str:
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_user_session(
    db: Session,
    user: User,
    ttl_seconds: int,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[UserSession, str]:
    """Persist a session row and return (row, raw_token). Raw token is
    returned ONLY here — callers must send it to the client once."""
    token = new_session_token()
    now = utcnow()
    row = UserSession(
        user_id=user.id,
        token_hash=hash_session_token(token),
        expires_at=now + timedelta(seconds=max(60, ttl_seconds)),
        created_at=now,
        last_used_at=now,
        ip=(ip or "")[:64] or None,
        user_agent=(user_agent or "")[:500] or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, token


def lookup_session(db: Session, token: str) -> tuple[UserSession, User] | None:
    """Validate an opaque session token. Returns (session, active_user)."""
    if not token:
        return None
    row = (
        db.query(UserSession)
        .filter(UserSession.token_hash == hash_session_token(token))
        .first()
    )
    if row is None:
        return None
    now = datetime.now(timezone.utc)
    exp = row.expires_at
    if exp is not None and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp is not None and exp <= now:
        return None
    user = db.get(User, row.user_id)
    if user is None or (user.status or "active") != "active":
        return None
    row.last_used_at = now
    user.last_login_at = user.last_login_at or now
    db.commit()
    return row, user


def revoke_session(db: Session, token: str) -> bool:
    row = (
        db.query(UserSession)
        .filter(UserSession.token_hash == hash_session_token(token))
        .first()
    )
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def revoke_all_user_sessions(db: Session, user_id: str) -> int:
    rows = db.query(UserSession).filter(UserSession.user_id == user_id).all()
    for row in rows:
        db.delete(row)
    db.commit()
    return len(rows)
