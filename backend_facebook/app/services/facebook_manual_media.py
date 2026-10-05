"""Manual-publish Facebook media resolver (Task 14).

Port of the "Snap Video" Apple Shortcut workflow (iCloud ID
254e64ee91184f79988aa5099b4dc3d7), audited action-by-action:

  GET {base}/json/snapvideo.json?api-key={key}&lang={lang}&ver=7
      &ask_format=false&show_menu=false&skip_update=true&b64={base64(url)}

Response: {"title", "thumbnail", "source", "medias": {label: file_url}}.
Entries like "{{open-url}}"/Close/guide images are filtered out; the first
surviving http(s) URL wins (server-side has no user to pick from a menu).

Used ONLY by manual publish. The auto pipeline keeps using
facebook_media.py / FastSaver untouched.

Security: the provider API key lives only in MANUAL_FB_PROVIDER_API_KEY
(env/Northflank). It is never logged, never committed, and never returned
to the browser. download_url stays server-side only.
"""

import base64
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from .facebook_media import (
    FacebookMediaError,
    ResolvedFacebookMedia,
    cleanup_job_dir,
    job_dir,
)

logger = logging.getLogger(__name__)

# Same UA the shortcut sends when downloading media.
PROVIDER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

MAX_BYTES = 1_000_000_000
CHUNK_SIZE = 1024 * 256

# Exact media label preferred by the proven client flow.
MP4_HD_LABEL = "🎬 MP4 HD"

# A provider "title" containing any of these is a usage notice, not the
# video caption: keep thumbnail/media, but null the caption.
WARNING_TITLE_HINTS = (
    "phím tắt chỉ dùng",
    "chỉ dùng cho mục đích cá nhân",
    "không reup",
)

# Typed errors for the manual resolver.
UNSUPPORTED = "MANUAL_RESOLVER_UNSUPPORTED"
TIMEOUT = "MANUAL_RESOLVER_TIMEOUT"
AUTH_FAILED = "MANUAL_RESOLVER_AUTH_FAILED"
RATE_LIMITED = "MANUAL_RESOLVER_RATE_LIMITED"
INVALID_RESPONSE = "MANUAL_RESOLVER_INVALID_RESPONSE"
TEMPORARY = "MANUAL_RESOLVER_TEMPORARY"
DOWNLOAD_FAILED = "MANUAL_DOWNLOAD_FAILED"

# Fallback-eligible: transient/temporary problems and per-URL limitations.
# Never fallback on validation errors (bad URL) or auth errors (bad key).
_FALLBACK_ELIGIBLE = frozenset(
    {TIMEOUT, TEMPORARY, RATE_LIMITED, INVALID_RESPONSE, UNSUPPORTED}
)

# Labels that are UI chrome / guide images, not video files.
_SKIP_LABEL_HINTS = ("close", "guide", "update", "{{open-url}}")


class ManualResolverError(Exception):
    """Typed manual-resolver error. Never carries keys or download URLs."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class ManualResolvedMedia:
    source_url: str
    download_url: str  # INTERNAL ONLY — never serialize to the browser.
    caption: str | None
    thumbnail_url: str | None
    duration: float | None
    provider: str


def _provider_config() -> tuple[str, str, str, float]:
    """Canonical PHIMTAT_* config with MANUAL_FB_* legacy fallback.

    Returns (api_base_url, redirect_url, api_key, timeout_seconds).
    Never logs or returns anything besides these four values.
    """
    from ..config import settings

    api_base = (settings.PHIMTAT_API_BASE_URL or "").strip()
    redirect_url = (settings.PHIMTAT_REDIRECT_URL or "").strip()
    if not api_base or not redirect_url:
        legacy_base = (settings.MANUAL_FB_PROVIDER_BASE_URL or "").strip().rstrip("/")
        if legacy_base:
            api_base = api_base or f"{legacy_base}/json/snapvideo.json"
            redirect_url = redirect_url or f"{legacy_base}/snapvideo/red64.php"
    api_key = (
        (settings.PHIMTAT_API_KEY or "").strip()
        or (settings.MANUAL_FB_PROVIDER_API_KEY or "").strip()
    )
    try:
        timeout = float(settings.PHIMTAT_TIMEOUT_SECONDS or 60)
    except (TypeError, ValueError):
        timeout = 60.0
    timeout = min(max(timeout, 5.0), 300.0)
    if not api_base or not redirect_url:
        raise ManualResolverError(AUTH_FAILED, "Manual provider endpoints are not configured.")
    if not api_key:
        raise ManualResolverError(
            AUTH_FAILED,
            "Manual provider API key is not configured. "
            "Set PHIMTAT_API_KEY (or use FACEBOOK_MANUAL_RESOLVER=shortcut_fastsaver).",
        )
    return api_base, redirect_url, api_key, timeout


def _pick_media_url(medias: object) -> str | None:
    """The proven client flow: medias["MP4 HD"] first, else any URL with
    .mp4, else the labeled MP4 entry, else the first surviving http URL."""
    if not isinstance(medias, dict):
        return None
    first_valid: str | None = None
    label_match: str | None = None
    for label, url in medias.items():
        if not isinstance(url, str):
            continue
        text = url.strip()
        if not text.lower().startswith(("http://", "https://")):
            continue
        lowered_label = str(label or "").lower()
        if any(hint in lowered_label for hint in _SKIP_LABEL_HINTS):
            continue
        if "{{open-url}}" in text.lower():
            continue
        if str(label or "") == MP4_HD_LABEL:
            return text
        # Direct file hints win immediately; a labeled MP4 entry (e.g.
        # "MP4 HD") is second choice; otherwise the first surviving http
        # URL — the downloader enforces content-type anyway.
        if ".mp4" in text.lower() or ".mov" in text.lower() or "red64.php" in text.lower():
            return text
        if "mp4" in lowered_label and label_match is None:
            label_match = text
        if first_valid is None:
            first_valid = text
    return label_match if label_match is not None else first_valid


def _filter_caption(title: object) -> str | None:
    """Provider usage notices are not video captions."""
    if not isinstance(title, str) or not title.strip():
        return None
    lowered = title.lower()
    if any(hint in lowered for hint in WARNING_TITLE_HINTS):
        return None
    if "snapvideo" in lowered:
        return None
    return title


# Facebook URL shapes accepted for manual mode. Bare profile/page URLs are
# rejected before any provider HTTP happens.
_VIDEO_MARKERS = ("/reel/", "/videos/", "/watch", "/share/")


def is_manual_video_url(raw_url: str | None) -> bool:
    from urllib.parse import urlparse

    from ..services.facebook_url import ALLOWED_HOSTS, is_facebook_url

    if not isinstance(raw_url, str) or not raw_url.strip():
        return False
    try:
        parsed = urlparse(raw_url.strip())
    except Exception:
        return False
    if (parsed.scheme or "").lower() not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    # Manual mode additionally accepts fb.watch short links. The shared
    # ALLOWED_HOSTS (auto pipeline) is intentionally left untouched.
    if host not in ALLOWED_HOSTS and host != "fb.watch":
        return False
    if host == "fb.watch":
        return True
    path = (parsed.path or "").lower()
    return any(m in path for m in _VIDEO_MARKERS)


# iPhone UA used to unwrap /share/ redirect wrappers into canonical URLs.
SHARE_RESOLVE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"
)
SHARE_RESOLVE_TIMEOUT = 15.0


async def resolve_share_url(
    url: str, transport: httpx.AsyncBaseTransport | None = None
) -> str:
    """/share/ links are redirect wrappers: follow them (iPhone UA) to the
    canonical /reel/ URL before calling the provider. Any failure returns
    the original URL — the provider gets the last word on validity."""
    try:
        async with httpx.AsyncClient(
            transport=transport,
            timeout=SHARE_RESOLVE_TIMEOUT,
            headers={"User-Agent": SHARE_RESOLVE_UA},
            follow_redirects=True,
        ) as client:
            resp = await client.get(url.strip())
            final = str(resp.url or "").strip()
            if final and "facebook.com" in final and "/share/" not in final:
                return final
    except Exception:
        pass
    return url.strip()


class ShortcutDerivedFacebookResolver:
    """phimtat/snapvideo adapter. One instance per resolve."""

    def __init__(
        self,
        api_base: str,
        redirect_url: str,
        api_key: str,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_base = api_base
        self.redirect_url = redirect_url
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            timeout=timeout,
            headers={"User-Agent": PROVIDER_UA},
            follow_redirects=True,
        )

    async def resolve(self, url: str) -> ManualResolvedMedia:
        if not is_manual_video_url(url):
            raise ManualResolverError(UNSUPPORTED, "Not a supported Facebook video URL.")
        from urllib.parse import quote

        # /share/ links wrap the real URL: unwrap first (iPhone UA), exactly
        # like the proven client flow. Falls back to the original URL.
        target = url.strip()
        if "/share/" in target.lower():
            target = await resolve_share_url(target, transport=self._transport)
        b64url = base64.b64encode(target.encode("utf-8")).decode("ascii")
        # Build the API URL exactly like the proven client flow, then fetch
        # it wrapped through red64.php (never GET the JSON endpoint directly).
        api_url = (
            f"{self.api_base}"
            f"?api-key={self._api_key}&lang=vi&ver=7"
            f"&ask_format=false&show_menu=false&skip_update=false"
            f"&b64={b64url}"
        )
        wrapped = base64.b64encode(api_url.encode("utf-8")).decode("ascii")
        fetch_url = f"{self.redirect_url}?url={quote(wrapped, safe='')}"
        try:
            async with self._client(self._timeout) as client:
                resp = await client.get(fetch_url)
        except httpx.TimeoutException:
            raise ManualResolverError(TIMEOUT, "Manual provider resolve timed out.")
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise ManualResolverError(TEMPORARY, f"Manual provider unreachable: {type(exc).__name__}.")
        if resp.status_code in (401, 403):
            raise ManualResolverError(AUTH_FAILED, "Manual provider rejected the API key.")
        if resp.status_code == 429:
            raise ManualResolverError(RATE_LIMITED, "Manual provider rate limited.")
        if 500 <= resp.status_code <= 599:
            raise ManualResolverError(TEMPORARY, f"Manual provider error ({resp.status_code}).")
        if resp.status_code != 200:
            raise ManualResolverError(
                INVALID_RESPONSE, f"Manual provider returned {resp.status_code}."
            )
        try:
            data = resp.json()
        except ValueError:
            raise ManualResolverError(INVALID_RESPONSE, "Manual provider returned invalid JSON.")
        if not isinstance(data, dict):
            raise ManualResolverError(INVALID_RESPONSE, "Manual provider response is not an object.")
        media_url = _pick_media_url(data.get("medias"))
        if not media_url:
            raise ManualResolverError(
                UNSUPPORTED, "Provider has no downloadable media for this URL."
            )
        thumbnail = data.get("thumbnail")
        caption = _filter_caption(data.get("title"))
        return ManualResolvedMedia(
            source_url=url.strip(),
            download_url=media_url,
            caption=caption,
            thumbnail_url=thumbnail if isinstance(thumbnail, str) else None,
            duration=None,
            provider="shortcut",
        )


async def _resolve_via_fastsaver(
    url: str, transport: httpx.AsyncBaseTransport | None
) -> ManualResolvedMedia:
    """Fallback only. Maps FastSaver errors onto manual codes."""
    from .facebook_media import FacebookMediaResolver

    try:
        resolver = FacebookMediaResolver.from_settings(transport=transport)
        media: ResolvedFacebookMedia = await resolver.resolve(url)
    except FacebookMediaError as exc:
        raise ManualResolverError("MANUAL_RESOLVER_FALLBACK_FAILED", str(exc))
    except RuntimeError as exc:
        raise ManualResolverError("MANUAL_RESOLVER_FALLBACK_FAILED", str(exc))
    return ManualResolvedMedia(
        source_url=url.strip(),
        download_url=media.download_url,
        caption=media.caption,
        thumbnail_url=media.thumbnail_url,
        duration=media.duration,
        provider="fastsaver",
    )


async def resolve_manual_media(
    url: str, transport: httpx.AsyncBaseTransport | None = None
) -> ManualResolvedMedia:
    """Dispatcher honoring FACEBOOK_MANUAL_RESOLVER.

    - "shortcut": shortcut-derived provider only, no fallback.
    - "shortcut_fastsaver": shortcut first, FastSaver fallback on
      timeout/temporary/rate-limit/invalid/unsupported — never on
      validation errors or auth errors.
    - "fastsaver": legacy FastSaver path (also what auto uses).
    """
    from ..config import settings

    if not is_manual_video_url(url):
        raise ManualResolverError(UNSUPPORTED, "Not a supported Facebook video URL.")
    mode = (settings.FACEBOOK_MANUAL_RESOLVER or "shortcut").strip().lower()
    if mode == "fastsaver":
        return await _resolve_via_fastsaver(url, transport)
    phimtat_on = bool(getattr(settings, "PHIMTAT_ENABLED", True))
    if mode == "shortcut_fastsaver":
        if not phimtat_on:
            return await _resolve_via_fastsaver(url, transport)
        try:
            api_base, redirect_url, api_key, timeout = _provider_config()
        except ManualResolverError:
            return await _resolve_via_fastsaver(url, transport)
        try:
            resolver = ShortcutDerivedFacebookResolver(
                api_base, redirect_url, api_key, timeout, transport=transport
            )
            return await resolver.resolve(url)
        except ManualResolverError as exc:
            if exc.code not in _FALLBACK_ELIGIBLE:
                raise
            logger.info("shortcut resolver %s, falling back to FastSaver", exc.code)
            return await _resolve_via_fastsaver(url, transport)
    # Strict shortcut mode.
    if not phimtat_on:
        raise ManualResolverError(UNSUPPORTED, "PHIMTAT provider is disabled (PHIMTAT_ENABLED=false).")
    api_base, redirect_url, api_key, timeout = _provider_config()
    resolver = ShortcutDerivedFacebookResolver(
        api_base, redirect_url, api_key, timeout, transport=transport
    )
    return await resolver.resolve(url)


async def download_manual_media(
    media: ManualResolvedMedia,
    job_id: str,
    transport: httpx.AsyncBaseTransport | None = None,
    tmp_root: Path | None = None,
) -> Path:
    """Stream the resolved download URL -> /tmp/facebook/<job_id>/video.mp4.

    Same guards as the auto path (content-type, size cap, chunked). The
    caller cleans up in finally.
    """
    from .facebook_media import TMP_ROOT as _DEFAULT_TMP

    root = tmp_root or _DEFAULT_TMP
    target_dir = job_dir(job_id, root)
    target_dir.mkdir(parents=True, exist_ok=True)
    output = target_dir / "video.mp4"
    if output.exists():
        output.unlink()
    timeout = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=30.0)
    received = 0
    try:
        async with httpx.AsyncClient(
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": PROVIDER_UA},
            follow_redirects=True,
        ) as client:
            async with client.stream("GET", media.download_url) as resp:
                if resp.status_code != 200:
                    raise ManualResolverError(
                        DOWNLOAD_FAILED, f"Media download failed ({resp.status_code})."
                    )
                content_type = (resp.headers.get("Content-Type", "") or "").lower().split(";")[0].strip()
                if content_type and (
                    not content_type.startswith("video/")
                    and content_type != "application/octet-stream"
                ):
                    raise ManualResolverError(
                        DOWNLOAD_FAILED, f"Unexpected media Content-Type: {content_type or 'missing'}."
                    )
                with output.open("wb") as fh:
                    async for chunk in resp.aiter_bytes(CHUNK_SIZE):
                        if not chunk:
                            continue
                        received += len(chunk)
                        if received > MAX_BYTES:
                            raise ManualResolverError(DOWNLOAD_FAILED, "Media exceeds max size.")
                        fh.write(chunk)
    except ManualResolverError:
        cleanup_job_dir(target_dir)
        raise
    except httpx.TimeoutException:
        cleanup_job_dir(target_dir)
        raise ManualResolverError(DOWNLOAD_FAILED, "Media download timed out.")
    if received <= 0:
        cleanup_job_dir(target_dir)
        raise ManualResolverError(DOWNLOAD_FAILED, "Downloaded file is empty.")
    return output
