"""Global platform accounts (Douyin/Facebook) shared across pipelines."""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.douyin_session_crypto import decrypt_text, encrypt_text
from app.models import PlatformAccount

logger = logging.getLogger("douyin-youtube-platform-accounts")

PLATFORMS = {"douyin", "facebook"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_platform_account(db: Session, platform: str) -> PlatformAccount | None:
    return db.get(PlatformAccount, platform) if False else db.execute(
        __import__("sqlalchemy").select(PlatformAccount).where(PlatformAccount.platform == platform).limit(1)
    ).scalar_one_or_none()


def ensure_platform_account(db: Session, platform: str) -> PlatformAccount:
    acct = get_platform_account(db, platform)
    if acct is not None:
        return acct
    acct = PlatformAccount(platform=platform, display_name=platform.capitalize(), status="needs_login")
    db.add(acct)
    db.commit()
    db.refresh(acct)
    return acct


def save_platform_credentials(db: Session, platform: str, raw: str, display_name: str | None = None) -> PlatformAccount:
    """Encrypt and store raw credentials (Netscape cookies.txt or JSON)."""
    if platform not in PLATFORMS:
        raise ValueError(f"Unsupported platform: {platform}")
    # Reuse Douyin cookie validation for douyin platform
    if platform == "douyin":
        from app.source_cookies import normalize_cookie_input, validate_cookie_text
        text = normalize_cookie_input(raw)
        meta = validate_cookie_text(text)
        enc = encrypt_text(text)
        acct = ensure_platform_account(db, platform)
        acct.credentials_encrypted = enc
        acct.status = "expired" if meta["looks_expired"] else "connected"
        acct.last_error = None
        acct.last_verified_at = None
        if display_name:
            acct.display_name = display_name
        db.commit()
        return acct
    # Facebook: store as-is encrypted (future validation)
    enc = encrypt_text(raw)
    acct = ensure_platform_account(db, platform)
    acct.credentials_encrypted = enc
    acct.status = "connected"
    acct.last_error = None
    if display_name:
        acct.display_name = display_name
    db.commit()
    return acct


def load_platform_credentials(platform: str) -> str | None:
    """Decrypt credentials for a platform (server-side only, never log)."""
    with SessionLocal() as db:
        acct = get_platform_account(db, platform)
        if acct is None or not acct.credentials_encrypted:
            return None
        try:
            return decrypt_text(acct.credentials_encrypted)
        except ValueError:
            return None


def load_platform_cookie_jar(platform: str) -> list[dict[str, Any]] | None:
    """For Douyin: return Playwright cookie jar or None."""
    if platform != "douyin":
        return None
    raw = load_platform_credentials(platform)
    if not raw:
        return None
    from app.douyin_inventory_providers import cookies_from_netscape_text
    try:
        return cookies_from_netscape_text(raw)
    except Exception:
        return None


def platform_public_status(db: Session, platform: str) -> dict[str, Any]:
    acct = get_platform_account(db, platform)
    if acct is None:
        return {"platform": platform, "status": "needs_login", "connected": False, "display_name": platform.capitalize()}
    return {
        "platform": acct.platform,
        "display_name": acct.display_name,
        "status": acct.status,
        "connected": acct.status == "connected",
        "last_verified_at": acct.last_verified_at.isoformat() if acct.last_verified_at else None,
        "last_error": acct.last_error,
        "created_at": acct.created_at.isoformat() if acct.created_at else None,
        "updated_at": acct.updated_at.isoformat() if acct.updated_at else None,
    }


def test_platform_account(db: Session, platform: str) -> dict[str, Any]:
    """Live test a platform account (Douyin: cookie-only profile fetch)."""
    acct = get_platform_account(db, platform)
    if acct is None or not acct.credentials_encrypted:
        raise RuntimeError(f"{platform} account not connected")
    if platform == "douyin":
        jar = load_platform_cookie_jar(platform)
        if not jar:
            raise RuntimeError("COOKIE_INVALID: cannot decrypt Douyin cookie")
        # Use a lightweight Douyin profile fetch to verify cookie
        from app.douyin_inventory_providers import PlaywrightDouyinInventoryProvider
        provider = PlaywrightDouyinInventoryProvider()
        # Use a known public profile as probe (Daniel Xu sec_uid or generic)
        # If no source exists, just check cookie looks valid (already validated)
        # For now, try to fetch with a dummy sec_uid that requires auth
        try:
            from app.models import DouyinSource
            src = db.execute(__import__("sqlalchemy").select(DouyinSource).limit(1)).scalar_one_or_none()
            sec_uid = src.douyin_sec_uid if src and src.douyin_sec_uid else "MS4wLjABAAAAtest"
            videos, _ = provider.fetch_latest("https://www.douyin.com/user/" + sec_uid, sec_uid, "test", cookie_jar=jar, only_cookies=True)
            acct.status = "connected"
            acct.last_verified_at = utcnow()
            acct.last_error = None
            db.commit()
            return {"ok": True, "platform": platform, "videos_probed": len(videos)}
        except Exception as exc:
            msg = str(exc)
            if "COOKIE_EXPIRED" in msg or "auth" in msg.lower():
                acct.status = "expired"
                acct.last_error = msg[:500]
                db.commit()
                raise RuntimeError(f"COOKIE_EXPIRED: {msg}") from exc
            acct.last_error = msg[:500]
            db.commit()
            raise RuntimeError(f"FETCH_FAILED: {msg}") from exc
    # Facebook stub
    acct.last_verified_at = utcnow()
    acct.status = "connected"
    db.commit()
    return {"ok": True, "platform": platform}
