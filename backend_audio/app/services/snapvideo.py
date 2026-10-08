"""SnapVideo/PHIMTAT resolver + streaming downloader (mirrors backend_facebook)."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger("backend-audio.snapvideo")

RESOLVE_FAILED = "SNAPVIDEO_RESOLVE_FAILED"
DOWNLOAD_FAILED = "SNAPVIDEO_DOWNLOAD_FAILED"
NOT_CONFIGURED = "SNAPVIDEO_NOT_CONFIGURED"


class SnapVideoError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _config() -> tuple[str, str, float, int]:
    from app.config import settings

    base = (settings.PHIMTAT_API_BASE_URL or "").strip()
    key = (settings.PHIMTAT_API_KEY or "").strip()
    if not settings.PHIMTAT_ENABLED:
        raise SnapVideoError(NOT_CONFIGURED, "PHIMTAT is disabled.")
    if not base or not key:
        raise SnapVideoError(NOT_CONFIGURED, "PHIMTAT_API_KEY / base URL missing.")
    return base, key, float(settings.PHIMTAT_TIMEOUT_SECONDS or 60), int(
        settings.PHIMTAT_MAX_BYTES or 500 * 1024 * 1024)


async def resolve_media_url(facebook_url: str,
                            transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Resolve a Facebook video URL to a direct mp4 URL + metadata."""
    base, key, timeout, _ = _config()
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout) as client:
            resp = await client.post(base, data={"url": facebook_url, "key": key})
    except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
        raise SnapVideoError(RESOLVE_FAILED, f"Resolver unreachable: {type(exc).__name__}.")
    if resp.status_code != 200:
        raise SnapVideoError(RESOLVE_FAILED, f"Resolver HTTP {resp.status_code}.")
    try:
        data = resp.json()
    except Exception:
        raise SnapVideoError(RESOLVE_FAILED, "Resolver returned non-JSON.")
    medias = data.get("medias") if isinstance(data, dict) else None
    picked = _pick_media_url(medias)
    if not picked:
        raise SnapVideoError(RESOLVE_FAILED, "No downloadable media in resolver response.")
    logger.info("resolved media in %.1fs", time.monotonic() - started)
    return {
        "media_url": picked,
        "title": data.get("title"),
        "thumbnail": data.get("thumbnail"),
        "duration": data.get("duration"),
    }


def _pick_media_url(medias: object) -> str | None:
    if not isinstance(medias, dict):
        return None
    fallback = None
    for label, url in medias.items():
        if not isinstance(url, str):
            continue
        text = url.strip()
        if not text.lower().startswith(("http://", "https://")):
            continue
        if str(label or "") == "MP4 HD":
            return text
        if ".mp4" in text.lower() and fallback is None:
            fallback = text
    return fallback


async def stream_download(media_url: str, dest: Path, max_bytes: int | None = None,
                          timeout: float = 300.0) -> Path:
    """Stream a direct media URL to disk with size cap. Never loads whole file."""
    _, _, _, default_max = _config()
    cap = max_bytes or default_max
    dest.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        async with httpx.AsyncClient(timeout=timeout,
                                     follow_redirects=True) as client:
            async with client.stream("GET", media_url) as resp:
                if resp.status_code != 200:
                    raise SnapVideoError(DOWNLOAD_FAILED,
                                         f"Media HTTP {resp.status_code}.")
                ctype = (resp.headers.get("content-type") or "").lower()
                if "video" not in ctype and "octet-stream" not in ctype:
                    raise SnapVideoError(
                        DOWNLOAD_FAILED, f"Unexpected content-type: {ctype}.")
                with open(dest, "wb") as fh:
                    async for chunk in resp.aiter_bytes(1024 * 256):
                        written += len(chunk)
                        if written > cap:
                            raise SnapVideoError(
                                DOWNLOAD_FAILED, "File exceeds size cap.")
                        fh.write(chunk)
    except SnapVideoError:
        raise
    except Exception as exc:
        raise SnapVideoError(DOWNLOAD_FAILED, f"Download error: {type(exc).__name__}.")
    if written == 0:
        raise SnapVideoError(DOWNLOAD_FAILED, "Empty download.")
    return dest
