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
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

SNAPVIDEO_ENDPOINT = "/json/snapvideo.json"
PROVIDER_TIMEOUT = 25.0
MAX_BYTES = 1_000_000_000
CHUNK_SIZE = 1024 * 256

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


def _provider_config() -> tuple[str, str]:
    from ..config import settings

    base_url = (settings.MANUAL_FB_PROVIDER_BASE_URL or "").strip().rstrip("/")
    api_key = (settings.MANUAL_FB_PROVIDER_API_KEY or "").strip()
    if not base_url:
        raise ManualResolverError(AUTH_FAILED, "Manual provider base URL is not configured.")
    if not api_key:
        raise ManualResolverError(
            AUTH_FAILED,
            "Manual provider API key is not configured. "
            "Set MANUAL_FB_PROVIDER_API_KEY (or use FACEBOOK_MANUAL_RESOLVER=shortcut_fastsaver).",
        )
    return base_url, api_key


def _pick_media_url(medias: object) -> str | None:
    """First usable file URL from the provider's medias map."""
    if not isinstance(medias, dict):
        return None
    fallback: str | None = None
    for label, url in medias.items():
        if not isinstance(url, str):
            continue
        text = url.strip()
        if not text.lower().startswith(("http://", "https://")):
            continue
        lowered_label = str(label or "").lower()
        if any(hint in lowered_label for hint in _SKIP_LABEL_HINTS):
            continue
        if any(hint in text.lower() for hint in ("{{open-url}}",)):
            continue
        # Prefer probable video files, but keep the first http URL as
        # fallback — the downloader enforces content-type anyway.
        if ".mp4" in text.lower() or ".mov" in text.lower() or "red64.php" in text.lower():
            return text
        if fallback is None:
            fallback = text
    return fallback


# Facebook URL shapes accepted for manual mode. Bare profile/page URLs are
# rejected before any provider HTTP happens.
_VIDEO_MARKERS = ("/reel/", "/videos/", "/watch", "/share/")


def is_manual_video_url(raw_url: str | None) -> bool:
    from urllib.parse import urlparse

    from ..services.facebook_url import is_facebook_url

    if not raw_url or not is_facebook_url(raw_url):
        return False
    try:
        parsed = urlparse(raw_url.strip())
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    if host == "fb.watch":
        return True
    path = (parsed.path or "").lower()
    return any(m in path for m in _VIDEO_MARKERS)


class ShortcutDerivedFacebookResolver:
    """phimtat/snapvideo adapter. One instance per resolve."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self._api_key = api_key
        self._transport = transport

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            base_url=self.base_url,
            timeout=timeout,
            headers={"User-Agent": PROVIDER_UA, "Accept": "application/json"},
            follow_redirects=True,
        )

    async def resolve(self, url: str) -> ManualResolvedMedia:
        if not is_manual_video_url(url):
            raise ManualResolverError(UNSUPPORTED, "Not a supported Facebook video URL.")
        b64url = base64.b64encode(url.strip().encode("utf-8")).decode("ascii")
        params = {
            "api-key": self._api_key,
            "lang": "vi",
            "ver": "7",
            "ask_format": "false",
            "show_menu": "false",
            "skip_update": "true",
            "b64": b64url,
        }
        try:
            async with self._client(PROVIDER_TIMEOUT) as client:
                resp = await client.get(SNAPVIDEO_ENDPOINT, params=params)
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
        caption = data.get("title")
        # The provider's "title" is often an upsell notice, not a caption.
        if isinstance(caption, str) and "snapvideo" in caption.lower():
            caption = None
        return ManualResolvedMedia(
            source_url=url.strip(),
            download_url=media_url,
            caption=caption if isinstance(caption, str) else None,
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
    if mode == "shortcut_fastsaver":
        try:
            base_url, api_key = _provider_config()
        except ManualResolverError:
            return await _resolve_via_fastsaver(url, transport)
        try:
            resolver = ShortcutDerivedFacebookResolver(base_url, api_key, transport=transport)
            return await resolver.resolve(url)
        except ManualResolverError as exc:
            if exc.code not in _FALLBACK_ELIGIBLE:
                raise
            logger.info("shortcut resolver %s, falling back to FastSaver", exc.code)
            return await _resolve_via_fastsaver(url, transport)
    # Strict shortcut mode.
    base_url, api_key = _provider_config()
    resolver = ShortcutDerivedFacebookResolver(base_url, api_key, transport=transport)
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
