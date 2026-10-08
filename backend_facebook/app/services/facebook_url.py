"""Facebook Reels URL parsing + username Page ID resolution.

parse_facebook_reels_url stays pure (no network): numeric Page ID fast path.
resolve_page_id_from_url handles username/profile/share URLs by fetching the
public page HTML and verifying the authoritative userID/userVanity pairing.
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


# ---------- username -> Page ID resolution (network) ----------

RESOLVE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
RESOLVE_HEADERS = {
    "User-Agent": RESOLVE_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
}
RESOLVE_TIMEOUT = 25.0

# Authoritative pairing: the ID is only trusted when the page itself
# declares it next to the requested vanity (username).
_USERID_VANITY_RE = re.compile(
    r'"userID"\s*:\s*"(\d+)"\s*,\s*"userVanity"\s*:\s*"([^"]+)"'
)
_FALLBACK_ID_RES = (
    re.compile(r'"pageID"\s*:\s*"(\d+)"'),
    re.compile(r'"entity_id"\s*:\s*"(\d+)"'),
)


class PageResolutionError(ValueError):
    """Raised when a username URL cannot be resolved to a Page ID."""

    code = "PAGE_UNRESOLVABLE"


def extract_username_candidate(raw_url: str | None) -> str | None:
    """Return the username segment for page-like URLs, else None.

    Accepts facebook.com/<username>/reels/, /<username>/, /people/.../ID/
    (numeric, handled by the parser anyway), numeric /<ID>/..., and
    share links (returned as-is; caller follows redirects first).
    """
    if not raw_url or not isinstance(raw_url, str):
        return None
    try:
        parsed = urllib.parse.urlparse(raw_url.strip())
    except Exception:
        return None
    if (parsed.scheme or "").lower() not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS and host != "fb.watch":
        return None
    segments = [
        urllib.parse.unquote(seg)
        for seg in parsed.path.split("/")
        if seg.strip()
    ]
    if not segments:
        return None
    # Share links carry opaque codes, not usernames: resolve the redirect
    # first, then re-derive from the final URL.
    if host in ("fb.watch",) or segments[0].lower() in ("share", "sharer"):
        return None
    first = segments[0].lower()
    if first in ("reel", "watch", "share", "sharer", "people", "profile.php"):
        return None
    if _NUMERIC_RE.match(segments[0]):
        return None  # numeric: parser fast path, no resolution needed
    return segments[0]


def extract_page_id_from_html(html: str, username: str) -> str | None:
    """Authoritative ID extraction: userID must pair with the vanity.

    Returns None instead of guessing when the pairing is absent.
    """
    if not html or not username:
        return None
    want = username.strip().lower()
    for page_id, vanity in _USERID_VANITY_RE.findall(html):
        if vanity.strip().lower() == want and page_id and page_id != "0":
            return page_id
    # Fallback patterns only when the page unambiguously names the vanity
    # elsewhere in the document.
    if want and want in html.lower():
        for pattern in _FALLBACK_ID_RES:
            match = pattern.search(html)
            if match and match.group(1) != "0":
                return match.group(1)
    return None


async def resolve_page_id_from_url(
    raw_url: str,
    transport=None,
) -> dict[str, str]:
    """Resolve any supported Facebook URL to a numeric Page ID.

    Returns {"page_id", "username", "normalized_url"}. Raises
    InvalidFacebookUrlError (bad URL), PageResolutionError (valid URL but
    ID not resolvable — never fabricates an ID).
    """
    import httpx

    if not raw_url or not isinstance(raw_url, str) or not raw_url.strip():
        raise InvalidFacebookUrlError("URL is empty")
    url = raw_url.strip()
    if not is_facebook_url(url):
        # Allow fb.watch share links: resolve the redirect first.
        try:
            parsed = urllib.parse.urlparse(url)
        except Exception:
            raise InvalidFacebookUrlError("Malformed URL")
        if (parsed.hostname or "").lower() != "fb.watch":
            raise InvalidFacebookUrlError("Not a supported Facebook URL")
    try:
        async with httpx.AsyncClient(
            transport=transport,
            timeout=RESOLVE_TIMEOUT,
            headers=RESOLVE_HEADERS,
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
    except Exception as exc:
        raise PageResolutionError(
            f"Không tải được trang Facebook để xác định Page ID ({type(exc).__name__})."
        ) from exc
    if resp.status_code != 200:
        raise PageResolutionError(
            f"Facebook trả HTTP {resp.status_code} khi xác định Page ID."
        )
    html = resp.text
    username = extract_username_candidate(url)
    if username is None:
        # Possibly redirected (share links): re-derive from final URL.
        final_url = str(resp.url)
        username = extract_username_candidate(final_url)
        if username is not None:
            url = final_url
    if username is None:
        raise PageResolutionError(
            "URL này không chứa username để xác định Page ID."
        )
    page_id = extract_page_id_from_html(html, username)
    if page_id is None:
        raise PageResolutionError(
            f"Không xác định được Page ID cho '{username}'. Trang có thể riêng tư, "
            "đổi tên, hoặc Facebook chặn truy cập."
        )
    return {
        "page_id": page_id,
        "username": username,
        "normalized_url": f"https://www.facebook.com/{page_id}/reels/",
    }
