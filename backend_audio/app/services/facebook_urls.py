"""Facebook URL parsing + normalization (adapted from backend_facebook logic)."""

from __future__ import annotations

import re
from urllib.parse import urlparse


class FacebookUrlError(ValueError):
    pass


_FB_HOSTS = ("facebook.com", "www.facebook.com", "m.facebook.com",
             "fb.com", "fb.watch")


def is_facebook_url(raw: str | None) -> bool:
    try:
        host = (urlparse((raw or "").strip()).hostname or "").lower()
    except Exception:
        return False
    return host in _FB_HOSTS or host.endswith(".facebook.com")


def canonicalize_facebook_url(raw: str) -> str:
    """Normalize to https://www.facebook.com/<path> without query noise."""
    text = (raw or "").strip()
    if not text:
        raise FacebookUrlError("Empty URL.")
    if not is_facebook_url(text):
        raise FacebookUrlError("Not a Facebook URL.")
    parsed = urlparse(text if "://" in text else "https://" + text)
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
    return f"https://www.facebook.com{path}"


def parse_facebook_source_url(raw: str) -> dict[str, str]:
    """Accept page /reels/ URLs; return canonical + username candidate."""
    canonical = canonicalize_facebook_url(raw)
    path = urlparse(canonical).path.strip("/")
    parts = [p for p in path.split("/") if p]
    username = parts[0] if parts else ""
    if not username or username in ("reel", "watch", "share", "videos"):
        raise FacebookUrlError(
            "URL must point to a Facebook page (e.g. https://www.facebook.com/somepage/reels/)."
        )
    return {"canonical_url": canonical, "username": username}


def extract_facebook_video_id(url: str) -> str | None:
    """Best-effort numeric video id from common Facebook URL shapes."""
    text = (url or "").strip()
    for pattern in (r"/reel/(\d+)", r"/videos/(\d+)", r"/watch/\?v=(\d+)",
                    r"[?&]v=(\d+)", r"/(\d{10,})"):
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None
