"""Per-source Douyin cookie management for AUTO mode.

Cookies are accepted as Netscape cookies.txt text (or a JSON cookie export,
which is normalized first). They are stored Fernet-encrypted, never logged,
never returned by any API. Verification runs a live cookie-only profile
fetch; expiry maps to COOKIE_EXPIRED.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.douyin_inventory_providers import (
    DouyinAuthRequiredError,
    DouyinInventoryError,
    cookies_from_netscape_text,
    cookies_look_expired,
    discover_profile_videos,
    parse_netscape_cookies,
)
from app.douyin_session_crypto import decrypt_text, encrypt_text
from app.models import DouyinSource

logger = logging.getLogger("douyin-youtube-source-cookies")

# Cookie names that prove an authenticated Douyin web session.
AUTH_COOKIE_NAMES = {
    "sessionid",
    "sid_guard",
    "sid_tt",
    "uid_tt",
    "passport_auth_ss",
    "sid_dy",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_cookie_input(raw: str) -> str:
    """Accept Netscape cookies.txt or a JSON cookie export; return Netscape text."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("Cookie is empty")
    if text.startswith("[") or text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("Cookie JSON is invalid") from exc
        items = data if isinstance(data, list) else data.get("cookies", [])
        if not isinstance(items, list) or not items:
            raise ValueError("Cookie JSON has no cookies")
        lines = []
        for c in items:
            if not isinstance(c, dict):
                continue
            name = str(c.get("name", ""))
            if not name:
                continue
            dom = str(c.get("domain", ""))
            path = str(c.get("path", "/"))
            flag = "TRUE" if dom.startswith(".") else "FALSE"
            sec = "TRUE" if c.get("secure") else "FALSE"
            try:
                exp = int(c.get("expirationDate") or c.get("expires") or 0)
            except (TypeError, ValueError):
                exp = 0
            lines.append("\t".join([
                dom, flag, path, sec, str(exp), name, str(c.get("value", "")),
            ]))
        if not lines:
            raise ValueError("Cookie JSON has no usable cookies")
        return "\n".join(lines) + "\n"
    return text if text.endswith("\n") else text + "\n"


def validate_cookie_text(text: str) -> dict[str, Any]:
    """Parse + sanity-check cookie text. Returns metadata (no values)."""
    parsed = parse_netscape_cookies(text)
    if not parsed:
        raise ValueError("No cookies parsed (invalid Netscape format)")
    names = {str(c.get("name", "")) for c in parsed}
    auth_present = sorted(AUTH_COOKIE_NAMES & names)
    if not auth_present:
        raise ValueError(
            "No authenticated session cookies found "
            "(expected one of: sessionid, sid_guard, sid_tt, uid_tt)"
        )
    expired = cookies_look_expired(parsed)
    return {
        "count": len(parsed),
        "auth_cookies": auth_present,
        "looks_expired": expired,
    }


def save_source_cookie(db: Session, source: DouyinSource, raw: str) -> dict[str, Any]:
    """Validate, encrypt and store a per-source cookie. Returns public status."""
    text = normalize_cookie_input(raw)
    meta = validate_cookie_text(text)
    source.cookie_encrypted = encrypt_text(text)
    source.cookie_status = "expired" if meta["looks_expired"] else "configured"
    source.needs_reauth = bool(meta["looks_expired"])
    source.cookie_verified_at = None
    source.cookie_account_name = None
    db.commit()
    return cookie_public_status(source)


def cookie_public_status(source: DouyinSource) -> dict[str, Any]:
    """Public cookie state: never includes the cookie itself."""
    return {
        "configured": bool(source.cookie_encrypted),
        "status": source.cookie_status or "missing",
        "account_name": source.cookie_account_name,
        "verified_at": (
            source.cookie_verified_at.isoformat()
            if source.cookie_verified_at else None
        ),
        "needs_reauth": bool(source.needs_reauth),
    }


def delete_source_cookie(db: Session, source: DouyinSource) -> dict[str, Any]:
    source.cookie_encrypted = None
    source.cookie_status = "missing"
    source.cookie_account_name = None
    source.cookie_verified_at = None
    source.needs_reauth = False
    db.commit()
    return cookie_public_status(source)


def load_source_cookie_jar(source: DouyinSource) -> list[dict[str, Any]]:
    """Decrypt a source cookie into Playwright cookie dicts (server-side only)."""
    if not source.cookie_encrypted:
        raise ValueError("Source has no cookie configured")
    try:
        text = decrypt_text(source.cookie_encrypted)
    except ValueError as exc:
        raise ValueError("Source cookie cannot be decrypted") from exc
    return cookies_from_netscape_text(text)


def test_source_cookie(db: Session, source: DouyinSource) -> dict[str, Any]:
    """Live-verify a source cookie with a cookie-only profile fetch.

    Returns {ok, nickname, sec_uid, latest_aweme_id} or raises with a
    machine-readable code: COOKIE_EXPIRED / COOKIE_INVALID / FETCH_FAILED.
    """
    try:
        jar = load_source_cookie_jar(source)
    except ValueError as exc:
        raise RuntimeError(f"COOKIE_INVALID: {exc}") from exc

    profile_url = source.profile_url or ""
    sec_uid = source.douyin_sec_uid or source.douyin_user_id or ""
    if sec_uid and not profile_url:
        profile_url = f"https://www.douyin.com/user/{sec_uid}"
    if not profile_url and not sec_uid:
        raise RuntimeError("FETCH_FAILED: source has no profile URL")

    try:
        videos, _provider = discover_profile_videos(
            profile_url, sec_uid, source.id,
            full=False, cookie_jar=jar, only_cookies=True,
        )
    except DouyinAuthRequiredError as exc:
        source.cookie_status = "expired"
        source.needs_reauth = True
        db.commit()
        raise RuntimeError(f"COOKIE_EXPIRED: {exc}") from exc
    except DouyinInventoryError as exc:
        raise RuntimeError(f"FETCH_FAILED: {exc}") from exc

    if not videos:
        raise RuntimeError(
            "FETCH_FAILED: cookie-only fetch returned no videos "
            "(profile may be private or blocked)"
        )

    first = videos[0] if isinstance(videos[0], dict) else {}
    nickname = str(first.get("author") or "")[:200]
    latest_aweme_id = str(first.get("video_id") or "")

    source.cookie_status = "verified"
    source.cookie_account_name = nickname or None
    source.cookie_verified_at = utcnow()
    source.needs_reauth = False
    if sec_uid and not source.douyin_sec_uid:
        source.douyin_sec_uid = sec_uid
    db.commit()

    return {
        "ok": True,
        "nickname": nickname,
        "sec_uid": source.douyin_sec_uid or sec_uid,
        "latest_aweme_id": latest_aweme_id,
    }
