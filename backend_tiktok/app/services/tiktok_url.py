"""TikTok URL parsing and normalization."""

import re
from urllib.parse import urlparse

from ..config import settings

VIDEO_PATH_MARKERS = ("/video/", "/v/", "/embed/", "/@")


def clean_tiktok_username(raw: str | None) -> str | None:
    """Extract and validate clean TikTok username from username string or URL.

    Supports:
      - @username
      - username
      - https://www.tiktok.com/@username
      - https://www.tiktok.com/@username?param=1
      - tiktok.com/@username
      - https://www.tiktok.com/@username/video/12345
    """
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not raw:
        return None

    # Handle URLs with or without scheme
    if "tiktok.com" in raw.lower() or raw.startswith("http://") or raw.startswith("https://"):
        url = raw if (raw.startswith("http://") or raw.startswith("https://")) else f"https://{raw}"
        try:
            parsed = urlparse(url)
            parts = (parsed.path or "").strip("/").split("/")
            for part in parts:
                if part.startswith("@"):
                    u = part[1:].split("?")[0].split("&")[0].strip()
                    if u and re.match(r"^[a-zA-Z0-9_.-]{2,50}$", u):
                        return u
        except Exception:
            pass

    # Handle @username or plain username
    u = raw.lstrip("@").strip()
    if u and re.match(r"^[a-zA-Z0-9_.-]{2,50}$", u):
        return u
    return None


async def resolve_tiktok_input(raw: str | None) -> tuple[str, str]:
    """Resolve TikTok username and canonical profile URL from any input format.

    Handles @username, plain username, full profile URL, video URL, or shortened link.
    Returns (clean_username, canonical_profile_url).
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("TikTok username hoặc profile URL không được để trống")

    username = clean_tiktok_username(raw)
    if username:
        return username, f"https://www.tiktok.com/@{username}"

    # Handle shortened links (e.g. vt.tiktok.com / vm.tiktok.com)
    raw_clean = raw.strip()
    if any(h in raw_clean.lower() for h in ("vt.tiktok.com", "vm.tiktok.com", "t.tiktok.com")):
        url = raw_clean if raw_clean.startswith("http") else f"https://{raw_clean}"
        try:
            import httpx

            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                resp = await client.head(url)
                final_url = str(resp.url)
                resolved_user = clean_tiktok_username(final_url)
                if resolved_user:
                    return resolved_user, f"https://www.tiktok.com/@{resolved_user}"
        except Exception:
            pass

    raise ValueError(f"Không thể xác định tài khoản TikTok từ: {raw}")


def is_tiktok_url(raw_url: str | None) -> bool:
    if not isinstance(raw_url, str) or not raw_url.strip():
        return False
    try:
        parsed = urlparse(raw_url.strip())
    except Exception:
        return False
    if (parsed.scheme or "").lower() not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    return host in settings.allowed_hosts


def normalize_url(raw_url: str) -> str:
    """Strip query params / fragments for stable dedup hashing."""
    if not is_tiktok_url(raw_url):
        return raw_url.strip()
    parsed = urlparse(raw_url.strip())
    clean = parsed._replace(query="", fragment="")
    return clean.geturl()


def extract_username(raw_url: str) -> str | None:
    """Extract @username from a TikTok profile or video URL."""
    if not is_tiktok_url(raw_url):
        return None
    parsed = urlparse(raw_url.strip())
    parts = (parsed.path or "").strip("/").split("/")
    for part in parts:
        if part.startswith("@"):
            return part[1:].split("?")[0]
    return None


def extract_video_id(raw_url: str) -> str | None:
    """Extract the numeric video ID from a TikTok URL."""
    if not is_tiktok_url(raw_url):
        return None
    parsed = urlparse(raw_url.strip())
    parts = (parsed.path or "").strip("/").split("/")
    for i, part in enumerate(parts):
        if part == "video" and i + 1 < len(parts):
            return parts[i + 1]
        if part == "v" and i + 1 < len(parts):
            return parts[i + 1]
    # vm.tiktok.com / vt.tiktok.com short links: fallback to last numeric segment
    for part in reversed(parts):
        if part.isdigit():
            return part
    return None
