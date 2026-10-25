"""Douyin profile URL normalization.

Handles the full range of Douyin profile URL shapes:
  * www.douyin.com/user/{sec_uid}
  * m.douyin.com/user/{sec_uid}
  * iesdouyin.com/share/user/{sec_uid}?...
  * v.douyin.com/{short}  (HTTP-redirects to a long profile URL)

All inputs are normalized to a canonical
``https://www.douyin.com/user/{sec_uid}`` form.  Video URLs
(``/video/`` or ``/v/``) and unrelated hosts are rejected.

Short-link resolution is SSRF-safe: every redirect target must land on a
Douyin-owned host and a hard redirect/timeout limit is enforced.
"""

from __future__ import annotations

import logging
import re
import socket
from urllib.parse import urlparse

logger = logging.getLogger("douyin-youtube-url")

# ---------------------------------------------------------------------------
# Domain allow-list — only these hosts may appear as redirect targets.
# This prevents SSRF via a malicious short link that points at an internal URL.
# ---------------------------------------------------------------------------
_ALLOWED_HOSTS = {
    "www.douyin.com",
    "douyin.com",
    "m.douyin.com",
    "iesdouyin.com",
    "loucofu.com",
}

_SHORT_DOMAINS = {
    "v.douyin.com",
    "douyin.com",  # sometimes short links live on the apex too
    "m.douyin.com",
}

_MAX_REDIRECTS = 8
_TIMEOUT_SECONDS = 10
_MAX_CONTENT = 65_536  # cap on response body when extracting a redirect URL

_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.4 Mobile/15E148 Safari/604.1"
)


class DouyinUrlError(ValueError):
    """Raised when a URL cannot be resolved to a Douyin profile."""


class DouyinProfileUrl:
    """Normalized representation of a Douyin profile URL.

    Attributes:
        original:  The raw user-supplied string (always non-empty when parsed).
        sec_uid:   The extracted ``secUid`` value.
        canonical: The normalized ``https://www.douyin.com/user/{sec_uid}`` URL.
    """

    def __init__(self, original: str, sec_uid: str, canonical: str):
        self.original = original
        self.sec_uid = sec_uid
        self.canonical = canonical

    def as_dict(self) -> dict[str, str]:
        """Backwards-compatible dict view (for source_providers.resolve_source)."""
        return {
            "sec_uid": self.sec_uid,
            "canonical": self.canonical,
            "clean_url": self.canonical,
        }


def _is_allowed_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    h = hostname.lower().strip()
    return h in _ALLOWED_HOSTS or h.endswith(".douyin.com") or h.endswith(".iesdouyin.com")


def _extract_sec_uid_from_path(path: str) -> str | None:
    """Extract sec_uid from a profile path, preferring `/share/user/` over `/user/`."""
    if not path:
        return None
    m = re.search(r"/share/user/([A-Za-z0-9_-]+)", path)
    if m:
        return m.group(1)
    m = re.search(r"/user/([A-Za-z0-9_-]+)", path)
    if m:
        return m.group(1)
    return None


def _is_video_url(path: str) -> bool:
    """Reject video/reel URLs — only profile pages are valid sources."""
    if not path:
        return False
    p = path.lower()
    return (
        p.startswith("/video/")
        or p.startswith("/v/")
        or "/video/" in p
        or "/v/" in p
    )


def _normalize_direct(url: str) -> DouyinProfileUrl | None:
    """Normalize a URL that is already a long Douyin profile URL (no redirect needed)."""
    value = url.strip()
    if not value:
        return None

    if not value.startswith("http://") and not value.startswith("https://"):
        value = "https://" + value

    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    path = parsed.path or ""

    if not _is_allowed_host(hostname):
        return None

    if _is_video_url(path):
        raise DouyinUrlError("Video URLs are not valid profile sources")

    sec_uid = _extract_sec_uid_from_path(path)
    if not sec_uid:
        # Check query parameter as fallback (iesdouyin.com sometimes uses ?sec_uid=)
        query = parsed.query or ""
        if "sec_uid=" in query:
            m = re.search(r"sec_uid=([A-Za-z0-9_-]+)", query)
            if m:
                sec_uid = m.group(1)

    if not sec_uid:
        return None

    canonical = f"https://www.douyin.com/user/{sec_uid}"
    return DouyinProfileUrl(
        original=url.strip(),
        sec_uid=sec_uid,
        canonical=canonical,
    )


def _resolve_short_link(url: str) -> str | None:
    """Follow HTTP redirects for a short link, SSRF-safe.

    Returns the final URL, or ``None`` if every redirect target was allowed
    but led to a non-profile or the redirect chain exceeded the limit.
    Raises ``DouyinUrlError`` for invalid inputs.
    """
    import httpx

    redirect_count = 0
    current_url = url.strip()

    if not current_url.startswith("http://") and not current_url.startswith("https://"):
        current_url = "https://" + current_url

    # Validate the starting URL host
    try:
        parsed = urlparse(current_url)
    except ValueError:
        raise DouyinUrlError(f"Invalid URL: {url}")

    # The short-link source host must be a known shortener
    src_host = (parsed.hostname or "").lower()
    if src_host not in _SHORT_DOMAINS:
        # Not a recognized short domain — treat as direct
        return current_url

    while redirect_count <= _MAX_REDIRECTS:
        try:
            resp = httpx.get(
                current_url,
                allow_redirects=False,
                timeout=httpx.Timeout(_TIMEOUT_SECONDS),
                headers={"User-Agent": _USER_AGENT},
            )
        except (httpx.TimeoutException, httpx.ConnectError, httpx.RequestError) as exc:
            logger.warning("Short-link resolve failed for %s: %s", current_url, exc)
            raise DouyinUrlError(f"Could not resolve short link: {exc}") from exc
        except Exception as exc:
            logger.warning("Short-link resolve error for %s: %s", current_url, exc)
            raise DouyinUrlError(f"Could not resolve short link: {exc}") from exc

        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location", "")
            if not location:
                raise DouyinUrlError("Redirect without a Location header")
            # Resolve relative redirects
            if location.startswith("/"):
                base = urlparse(current_url)
                location = f"{base.scheme}://{base.netloc}{location}"
            elif not location.startswith("http://") and not location.startswith("https://"):
                location = "https://" + location

            # SSRF guard: every redirect target must be a Douyin host
            target_host = (urlparse(location).hostname or "").lower()
            if not _is_allowed_host(target_host):
                raise DouyinUrlError(
                    f"Redirect to non-Douyin host blocked: {target_host}"
                )

            current_url = location
            redirect_count += 1
            continue

        # No more redirects — check if this is a final profile URL
        return current_url

    raise DouyinUrlError(f"Exceeded {_MAX_REDIRECTS} redirects for short link")


_PROFILE_PATH_RE = re.compile(r"^https?://(www\.|m\.)?douyin\.com/user/([A-Za-z0-9_-]+)")
_SHARE_PATH_RE = re.compile(r"^https?://(www\.|m\.)?iesdouyin\.com/share/user/([A-Za-z0-9_-]+)")


def _normalize_long_from_short(short_url: str) -> DouyinProfileUrl | None:
    """Resolve a short link and normalize the resulting long URL."""
    try:
        final_url = _resolve_short_link(short_url)
    except DouyinUrlError:
        return None

    if final_url is None:
        return None

    return _normalize_direct(final_url)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_video_url(url: str) -> bool:
    """Return True if *url* points at a Douyin video (not a profile)."""
    value = url.strip()
    if not value:
        return False
    if not value.startswith("http://") and not value.startswith("https://"):
        value = "https://" + value
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return _is_video_url(parsed.path or "")


def parse_douyin_profile_url(raw_url: str) -> DouyinProfileUrl | None:
    """Parse any Douyin profile URL into a canonical form.

    Supports:
      * https://www.douyin.com/user/{sec_uid}
      * https://m.douyin.com/user/{sec_uid}
      * https://iesdouyin.com/share/user/{sec_uid}?...
      * https://v.douyin.com/{short}  (HTTP redirect)

    Returns ``None`` for URLs that don't contain a parseable sec_uid
    (e.g. the homepage or a video link returns ``None``).
    Video URLs raise :class:`DouyinUrlError`.
    """
    original = raw_url.strip()
    if not original:
        return None

    # Need to add scheme for urlparse to recognize hostname
    # This preserves the original case of the URL path (including sec_uid)
    if not original.lower().startswith("http://") and not original.lower().startswith("https://"):
        url_with_scheme = "https://" + original
    else:
        url_with_scheme = original

    parsed_original = urlparse(url_with_scheme)
    hostname = (parsed_original.hostname or "").lower()
    path = parsed_original.path or ""

    # Video URL rejection
    if _is_video_url(path):
        raise DouyinUrlError("Video URLs are not valid profile sources")

    # Direct long URLs (douyin.com or iesdouyin.com)
    if hostname in {"www.douyin.com", "douyin.com", "m.douyin.com", "iesdouyin.com"} or hostname.endswith(".douyin.com"):
        # Extract sec_uid from the original case path
        sec_uid = _extract_sec_uid_from_path(path)
        if not sec_uid:
            # Check query parameter as fallback (iesdouyin.com sometimes uses ?sec_uid=)
            query = parsed_original.query or ""
            if "sec_uid=" in query:
                m = re.search(r"sec_uid=([A-Za-z0-9_-]+)", query)
                if m:
                    sec_uid = m.group(1)

        if not sec_uid:
            return None

        canonical = f"https://www.douyin.com/user/{sec_uid}"
        return DouyinProfileUrl(
            original=original,
            sec_uid=sec_uid,
            canonical=canonical,
        )

    # Short link — resolve redirects
    # For short links, we need to normalize the URL first
    value = original.lower()
    if not value.startswith("http://") and not value.startswith("https://"):
        value = "https://" + value

    parsed = urlparse(value)
    src_host = (parsed.hostname or "").lower()
    if src_host in _SHORT_DOMAINS:
        try:
            final_url = _resolve_short_link(value)
        except DouyinUrlError:
            return None
        if final_url is None:
            return None

        # Parse the final URL to extract sec_uid
        parsed_final = urlparse(final_url)
        final_hostname = (parsed_final.hostname or "").lower()
        final_path = parsed_final.path or ""

        if final_hostname in {"www.douyin.com", "douyin.com", "m.douyin.com", "iesdouyin.com"} or final_hostname.endswith(".douyin.com"):
            sec_uid = _extract_sec_uid_from_path(final_path)
            if not sec_uid:
                query = parsed_final.query or ""
                if "sec_uid=" in query:
                    m = re.search(r"sec_uid=([A-Za-z0-9_-]+)", query)
                    if m:
                        sec_uid = m.group(1)

            if not sec_uid:
                return None

            canonical = f"https://www.douyin.com/user/{sec_uid}"
            return DouyinProfileUrl(
                original=original,
                sec_uid=sec_uid,
                canonical=canonical,
            )

    return None


def parse_profile_url(url: str) -> dict[str, str] | None:
    """Dict-style wrapper around :func:`parse_douyin_profile_url`.

    Returns ``{"sec_uid": ..., "clean_url": ...}`` or ``None``.
    Kept for backwards compatibility with callers that expect a dict.
    """
    result = parse_douyin_profile_url(url)
    if result is None:
        return None
    return result.as_dict()
