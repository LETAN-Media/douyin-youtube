"""TikTok URL parsing and normalization."""

from urllib.parse import urlparse

from ..config import settings

VIDEO_PATH_MARKERS = ("/video/", "/v/", "/embed/", "/@")


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
