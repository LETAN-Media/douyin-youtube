"""TikTok media resolver for the manual-publish path.

Uses the PHIMTAT shortcut-derived provider (same as backend_facebook's
manual resolver) configured via PHIMTAT_* env vars.  The auto pipeline
uses the normal download path via the provider adapter.
"""

import base64
import hashlib
import ipaddress
import logging
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ..config import settings
from .tiktok_provider import TikTokMedia
from .tiktok_url import is_tiktok_url, normalize_url

logger = logging.getLogger("backend-tiktok.services.manual_media")

PROVIDER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

MAX_BYTES = 1_000_000_000
CHUNK_SIZE = 256 * 1024
SSRF_MAX_REDIRECTS = 6


def _assert_public_http_url(url: str) -> None:
    """SSRF guard: http(s) only, host must not resolve to private/loopback."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ManualMediaError(DOWNLOAD_FAILED, "Media URL is not public HTTP(S).")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        raise ManualMediaError(DOWNLOAD_FAILED, "Media host does not resolve.")
    for info in infos:
        try:
            if ipaddress.ip_address(info[4][0]).is_private:
                raise ManualMediaError(DOWNLOAD_FAILED,
                                       "Media host resolves to a private address.")
        except ValueError:
            continue


@dataclass
class ManualResolvedMedia:
    source_url: str
    download_url: str
    content_type: str
    caption: str | None
    thumbnail_url: str | None
    duration: int | None = None
    provider: str = "shortcut"


def source_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()[:32]


class ManualMediaError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


UNSUPPORTED = "TIKTOK_MANUAL_UNSUPPORTED"
TIMEOUT = "TIKTOK_MANUAL_TIMEOUT"
RATE_LIMITED = "TIKTOK_MANUAL_RATE_LIMITED"
TEMPORARY = "TIKTOK_MANUAL_TEMPORARY"
INVALID_RESPONSE = "TIKTOK_MANUAL_INVALID_RESPONSE"
DOWNLOAD_FAILED = "TIKTOK_MANUAL_DOWNLOAD_FAILED"


_FALLBACK_ELIGIBLE = frozenset(
    {TIMEOUT, TEMPORARY, RATE_LIMITED, INVALID_RESPONSE, UNSUPPORTED}
)


def _provider_config() -> tuple[str, str, str, float]:
    api_base = (settings.phimtat_api_base_url or "").strip()
    redirect_url = (settings.phimtat_redirect_url or "").strip()
    api_key = (settings.phimtat_api_key or "").strip()
    try:
        timeout = float(settings.phimtat_timeout_seconds or 60)
    except (TypeError, ValueError):
        timeout = 60.0
    timeout = min(max(timeout, 5.0), 300.0)
    if not api_base or not redirect_url:
        raise ManualMediaError("TIKTOK_MANUAL_AUTH_FAILED", "PHIMTAT endpoints not configured.")
    if not api_key:
        raise ManualMediaError(
            "TIKTOK_MANUAL_AUTH_FAILED",
            "PHIMTAT_API_KEY is not configured. Set PHIMTAT_API_KEY.",
        )
    return api_base, redirect_url, api_key, timeout


async def resolve_shortcut_media(
    url: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ManualResolvedMedia:
    """Resolve a TikTok URL via the PHIMTAT shortcut-derived provider."""
    if not is_tiktok_url(url):
        raise ManualMediaError(UNSUPPORTED, "Not a supported TikTok video URL.")
    api_base, redirect_url, api_key, timeout = _provider_config()
    b64url = base64.b64encode(url.strip().encode("utf-8")).decode("ascii")
    api_url = (
        f"{api_base}"
        f"?api-key={api_key}&lang=vi&ver={settings.phimtat_ver or '8'}"
        f"&ask_format=true&show_menu=true&skip_update=false"
        f"&b64={b64url}"
    )
    try:
        async with httpx.AsyncClient(
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": PROVIDER_UA},
            follow_redirects=True,
        ) as client:
            wrapped = base64.b64encode(
                api_url.encode("utf-8")
            ).decode("ascii")
            fetch_url = f"{redirect_url}?url={wrapped}"
            resp = await client.get(fetch_url)
            if resp.status_code in (401, 403):
                raise ManualMediaError("TIKTOK_MANUAL_AUTH_FAILED", "Provider rejected the API key.")
            if resp.status_code == 429:
                raise ManualMediaError(RATE_LIMITED, "Provider rate limited.")
            if 500 <= resp.status_code <= 599:
                raise ManualMediaError(TEMPORARY, f"Provider error ({resp.status_code}).")
            if resp.status_code != 200:
                raise ManualMediaError(INVALID_RESPONSE, f"Provider returned {resp.status_code}.")
            try:
                data = resp.json()
            except ValueError:
                raise ManualMediaError(INVALID_RESPONSE, "Invalid JSON from provider.")
            if not isinstance(data, dict):
                raise ManualMediaError(INVALID_RESPONSE, "Response is not an object.")
    except httpx.TimeoutException:
        raise ManualMediaError(TIMEOUT, "Provider resolve timed out.")
    except (httpx.ConnectError, httpx.NetworkError) as exc:
        raise ManualMediaError(TEMPORARY, f"Provider unreachable: {type(exc).__name__}.")

    media_url = _extract_download_url(data)
    if not media_url:
        raise ManualMediaError(UNSUPPORTED, "Provider has no downloadable media for this URL.")
    return ManualResolvedMedia(
        source_url=url.strip(),
        download_url=media_url,
        content_type=data.get("content_type", "video/mp4"),
        caption=_extract_caption(data),
        thumbnail_url=data.get("thumbnail") or data.get("cover"),
        duration=data.get("duration"),
        provider="shortcut",
    )


def _extract_download_url(data: dict) -> str | None:
    medias = data.get("medias") or {}
    if isinstance(medias, dict):
        for label, value in medias.items():
            url = value.get("url") if isinstance(value, dict) else value
            if isinstance(url, str) and url.startswith("http"):
                return url
    for key in ("download_url", "play", "nwm_url", "url", "playAddr"):
        v = data.get(key)
        if isinstance(v, str) and v.startswith("http"):
            return v
    return None


def _extract_caption(data: dict) -> str | None:
    title = data.get("title")
    if isinstance(title, str) and title.strip():
        return title
    desc = data.get("desc") or data.get("description") or data.get("caption")
    if isinstance(desc, str) and desc.strip():
        return desc
    return None


async def download_media(
    media: ManualResolvedMedia,
    job_id: str,
    tmp_root: Path | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    skip_ssrf_check: bool = False,
) -> Path:
    """Stream the resolved URL to /tmp/tiktok/<job_id>/video.mp4.

    Validates each redirect hop (SSRF), content-type, and enforces a size cap.
    Set ``skip_ssrf_check=True`` only for trusted local URLs in tests.
    """
    root = tmp_root or settings.tmp_root
    target_dir = root / job_id
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
            follow_redirects=False,
        ) as client:
            url = media.download_url
            for _ in range(SSRF_MAX_REDIRECTS):
                if not skip_ssrf_check:
                    _assert_public_http_url(url)
                async with client.stream("GET", url) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        location = resp.headers.get("location")
                        if not location:
                            raise ManualMediaError(DOWNLOAD_FAILED, "Empty redirect.")
                        url = location
                        continue
                    if resp.status_code != 200:
                        raise ManualMediaError(
                            DOWNLOAD_FAILED, f"Media download failed ({resp.status_code})."
                        )
                    content_type = (resp.headers.get("Content-Type", "") or "").lower().split(";")[0].strip()
                    if content_type and not content_type.startswith("video/") and content_type != "application/octet-stream":
                        raise ManualMediaError(
                            DOWNLOAD_FAILED, f"Unexpected Content-Type: {content_type or 'missing'}."
                        )
                    with output.open("wb") as fh:
                        async for chunk in resp.aiter_bytes(CHUNK_SIZE):
                            if not chunk:
                                continue
                            received += len(chunk)
                            if received > MAX_BYTES:
                                raise ManualMediaError(DOWNLOAD_FAILED, "Media exceeds max size.")
                            fh.write(chunk)
                    break
            else:
                raise ManualMediaError(DOWNLOAD_FAILED, "Too many redirects.")
    except ManualMediaError:
        _cleanup(target_dir)
        raise
    except httpx.TimeoutException:
        _cleanup(target_dir)
        raise ManualMediaError(DOWNLOAD_FAILED, "Media download timed out.")
    if received <= 0:
        _cleanup(target_dir)
        raise ManualMediaError(DOWNLOAD_FAILED, "Downloaded file is empty.")
    return output


def _cleanup(target_dir: Path) -> None:
    import shutil

    try:
        shutil.rmtree(target_dir, ignore_errors=True)
    except Exception:
        pass


async def resolve_manual_media(url: str) -> ManualResolvedMedia:
    """Dispatcher honoring TIKTOK_MANUAL_RESOLVER."""
    mode = (settings.tiktok_manual_resolver or "shortcut").strip().lower()
    if mode == "shortcut":
        return await resolve_shortcut_media(url)
    # Fallback to direct provider for 'direct' mode.
    from .tiktok_provider_factory import get_scan_provider

    provider = get_scan_provider()
    media = await provider.resolve_media(url)
    return ManualResolvedMedia(
        source_url=media.source_url,
        download_url=media.download_url,
        content_type=media.content_type,
        caption=media.caption,
        thumbnail_url=media.thumbnail_url,
        duration=media.duration,
        provider=provider.name,
    )
