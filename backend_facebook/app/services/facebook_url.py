"""Facebook Reels URL parsing service (Task 3).

No network calls. No crawling. Pure URL validation / normalization.
"""

from __future__ import annotations

import re
import urllib.parse

ALLOWED_HOSTS = frozenset({"facebook.com", "www.facebook.com", "m.facebook.com"})

SOURCE_TYPE = "facebook_reels"

_NUMERIC_RE = re.compile(r"^\d+$")

PAGE_ID_REQUIRED_MESSAGE = (
    "URL không chứa numeric Facebook Page ID. "
    "Hãy dùng URL Reels có Page ID hoặc resolve Page ID ở bước sau."
)


class InvalidFacebookUrlError(ValueError):
    """Raised when the URL is not a valid Facebook URL."""

    code = "INVALID_FACEBOOK_URL"


class PageIdRequiredError(ValueError):
    """Raised when a valid Facebook URL has no numeric Page ID."""

    code = "PAGE_ID_REQUIRED"

    def __init__(self, message: str = PAGE_ID_REQUIRED_MESSAGE) -> None:
        super().__init__(message)


def _fail_invalid(message: str) -> None:
    raise InvalidFacebookUrlError(message)


def parse_facebook_reels_url(raw_url: str | None) -> dict[str, str]:
    """Validate + normalize a Facebook Reels source URL.

    Returns:
        {"page_id": ..., "normalized_url": ..., "source_type": "facebook_reels"}

    Raises:
        InvalidFacebookUrlError: hostname/scheme malformed or not Facebook.
        PageIdRequiredError: valid Facebook URL but no numeric Page ID.
    """
    if raw_url is None or not isinstance(raw_url, str):
        _fail_invalid("URL must be a string")
    url = raw_url.strip()
    if not url:
        _fail_invalid("URL is empty")

    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        _fail_invalid("Malformed URL")

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        _fail_invalid("URL must start with http:// or https://")

    host = (parsed.hostname or "").lower()
    if not host:
        _fail_invalid("URL has no hostname")
    if host not in ALLOWED_HOSTS:
        _fail_invalid(f"Not a supported Facebook host: {host}")

    try:
        segments = [
            urllib.parse.unquote(seg)
            for seg in parsed.path.split("/")
            if seg.strip()
        ]
    except Exception:
        _fail_invalid("Malformed URL path")

    page_id: str | None = None
    for seg in segments:
        if _NUMERIC_RE.match(seg):
            page_id = seg
            break

    if page_id is None:
        raise PageIdRequiredError()

    normalized_url = f"https://www.facebook.com/{page_id}/reels/"
    return {
        "page_id": page_id,
        "normalized_url": normalized_url,
        "source_type": SOURCE_TYPE,
    }


def is_facebook_url(raw_url: str | None) -> bool:
    """True if hostname is an allowed Facebook host with http(s) scheme."""
    if not raw_url or not isinstance(raw_url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(raw_url.strip())
    except Exception:
        return False
    if (parsed.scheme or "").lower() not in ("http", "https"):
        return False
    return (parsed.hostname or "").lower() in ALLOWED_HOSTS
