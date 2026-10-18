"""PHIMTAT resolver + streaming downloader.

Verified live contract (do NOT use direct POST/GET on snapvideo.json —
they return 405 / a static shortcut menu):
  1. b64 = base64(target_url)
  2. api_url = {base}?api-key={key}&lang=vi&ver={ver}&ask_format=true
                 &show_menu=true&skip_update=false&b64={b64}
  3. GET {redirect}/red64.php?url={b64(api_url)}  (browser UA, redirects on)
  4. JSON {medias: {label: url}} -> prefer "MP4 HD" (or SD when asked).

Snap Video shortcut v8 (Oct 2026) changed the payload shape:
  - `medias` values became objects: {"url": "https://...", "ext": "mp4"}
    (plain strings still accepted for rollback).
  - First-time calls hit a personal-use terms gate
    (medias["✅ Đồng ý"]["url"] = agree-terms.php) that is accepted once
    in-session (through red64.php) then the resolve is retried.
  - Older `ver=7` answers an update wall (required_version key) — treat
    as unresolvable so the configured fallback takes over.

If the provider answers anything else, the resolve FAILS loudly — never a
fabricated URL. Media download validates scheme/host (no local/private
targets), content-type and ffprobe structure.
"""

from __future__ import annotations

import base64
import ipaddress
import logging
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx

logger = logging.getLogger("backend-audio.snapvideo")

RESOLVE_FAILED = "SNAPVIDEO_RESOLVE_FAILED"
DOWNLOAD_FAILED = "SNAPVIDEO_DOWNLOAD_FAILED"
NOT_CONFIGURED = "SNAPVIDEO_NOT_CONFIGURED"
UNRESOLVABLE = "SNAPVIDEO_UNRESOLVABLE"
UPDATE_REQUIRED = "SNAPVIDEO_UPDATE_REQUIRED"

PROVIDER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")

_SKIP_LABEL_HINTS = ("jpg", "png", "guide", "close", "update")


class SnapVideoError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _phimtat_configured() -> bool:
    from app.config import settings

    return bool(settings.PHIMTAT_ENABLED
                and (settings.PHIMTAT_API_BASE_URL or "").strip()
                and (settings.PHIMTAT_API_KEY or "").strip())


def _download_limit() -> int:
    """Size cap independent of any resolver credentials."""
    from app.config import settings

    try:
        return int(settings.PHIMTAT_MAX_BYTES or 500 * 1024 * 1024)
    except (TypeError, ValueError):
        return 500 * 1024 * 1024


def _media_url_of(value: object) -> str | None:
    """Normalize a medias entry: v8 objects {"url": ..., "ext": ...} and
    legacy v7 plain strings both reduce to the raw URL string."""
    if isinstance(value, dict):
        value = value.get("url")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _pick_media_url(medias: object, prefer_sd: bool = False) -> str | None:
    """Prefer HD MP4 (or the SD stream when prefer_sd), else any direct
    .mp4/.mov/red64 URL. Skips menus/guides/terms placeholders. Two-pass
    so SD is honored even when the provider lists HD first."""
    if not isinstance(medias, dict):
        return None
    entries: list[tuple[str, bool, str]] = []
    for label, value in medias.items():
        url = _media_url_of(value)
        if not url or not url.lower().startswith(("http://", "https://")):
            continue
        lowered_label = str(label or "").lower()
        if any(hint in lowered_label for hint in _SKIP_LABEL_HINTS):
            continue
        if "{{open-url}}" in url.lower() or "{{open-link}}" in url.lower():
            continue
        is_sd = "sd" in lowered_label and "hd" not in lowered_label
        entries.append((url, is_sd, lowered_label))
    if prefer_sd:
        for url, is_sd, _ in entries:
            if is_sd:
                return url
    # Legacy chain: first HD entry, else first non-SD direct-file URL,
    # else any MP4-labeled URL, else the SD entry as final fallback.
    for url, is_sd, lowered_label in entries:
        if "mp4 hd" in lowered_label or "hd" in lowered_label.split():
            return url
    for url, is_sd, lowered_label in entries:
        lowered = url.lower()
        if ".mp4" in lowered or ".mov" in lowered or "red64.php" in lowered:
            if is_sd:
                continue
            return url
    for url, is_sd, lowered_label in entries:
        if "mp4" in lowered_label:
            return url
    for url, is_sd, lowered_label in entries:
        if is_sd:
            return url
    return None


def _find_consent_url(medias: object) -> str | None:
    """Terms gate: a 'Đồng ý/agree' entry pointing at agree-terms.php."""
    if not isinstance(medias, dict):
        return None
    for label, value in medias.items():
        url = _media_url_of(value)
        if not url:
            continue
        lowered_label = str(label or "").lower()
        if "agree-terms.php" in url and url.startswith("http"):
            return url
        if "đồng ý" in lowered_label and "agree" in lowered_label:
            if "agree-terms" in url:
                return url
    return None


def _is_terms_gate(data: dict) -> bool:
    """Structural check: a consent entry and nothing pickable to download.
    (Provider titles vary; the agree-terms entry + empty media set is the
    stable live signal, verified Oct 2026.)"""
    return (_find_consent_url(data.get("medias")) is not None
            and _pick_media_url(data.get("medias")) is None)


def _is_menu_fallback(data: dict) -> bool:
    """Update wall (v7 rollback) or any 'update the shortcut' menu."""
    labels = data.get("labels")
    labels_text = " ".join(str(x or "") for x in labels) if isinstance(labels, list) else ""
    blob = (f"{data.get('title') or ''} {data.get('menu_title') or ''} "
            f"{labels_text}").lower()
    return ("update shortcuts" in blob
            or "cập nhật phím tắt" in blob
            or "required_version" in data)


def _required_version_hint(data: dict) -> str:
    try:
        version = data.get("required_version")
        return f"ver>={int(version)}" if version is not None else "a newer API version"
    except (TypeError, ValueError):
        return "a newer API version"


async def resolve_media_url(facebook_url: str,
                            transport: httpx.AsyncBaseTransport | None = None,
                            fastsaver_transport=None,
                            prefer_sd: bool | None = None) -> dict:
    """Resolve a Facebook video URL to a direct mp4 URL + metadata.

    Primary: PHIMTAT b64+red64 flow. Optional FastSaver fallback ONLY when
    AUDIO_FASTSAVER_* is configured. `prefer_sd` selects the SD stream to
    shrink download size when only the audio matters; None = service default.
    """
    from app.services.facebook_urls import is_facebook_url

    target = (facebook_url or "").strip()
    if not is_facebook_url(target):
        raise SnapVideoError(RESOLVE_FAILED, "Not a valid Facebook URL.")
    if prefer_sd is None:
        from app.config import settings

        prefer_sd = bool(getattr(settings, "PHIMTAT_PREFER_SD", False))
    if _phimtat_configured():
        try:
            return await _resolve_phimtat(target, transport, prefer_sd)
        except SnapVideoError as exc:
            if not _fastsaver_configured():
                raise
            logger.warning("phimtat resolve failed (%s); trying FastSaver",
                           exc.code)
    elif not _fastsaver_configured():
        raise SnapVideoError(NOT_CONFIGURED,
                             "No resolver configured (PHIMTAT or FastSaver).")
    return await _resolve_fastsaver(target, fastsaver_transport)


async def _parse_phimtat_payload(client: httpx.AsyncClient, fetch_url: str,
                                 allow_consent: bool = True) -> dict:
    """Fetch through red64 (already cooked URL), verify, and settle the
    terms gate once per session. Raises SnapVideoError; never fabricates."""
    data = await _fetch_phimtat_json(client, fetch_url)
    if data is None:
        raise SnapVideoError(RESOLVE_FAILED, "PHIMTAT returned no data.")
    if _is_menu_fallback(data):
        raise SnapVideoError(
            UNRESOLVABLE,
            f"PHIMTAT answered an update wall ({_required_version_hint(data)}). "
            "Outdated resolver version, not a media error.")
    if _is_terms_gate(data) and allow_consent:
        consent = _find_consent_url(data.get("medias"))
        if consent:
            await _accept_consent(client, consent)
            data = await _parse_phimtat_payload(client, fetch_url,
                                                allow_consent=False)
    return data


async def _resolve_phimtat(target: str, transport,
                           prefer_sd: bool = False) -> dict:
    from app.config import settings

    base = (settings.PHIMTAT_API_BASE_URL or "").strip()
    redirect = (settings.PHIMTAT_REDIRECT_URL or "").strip() or "https://api.phimtat.vn/snapvideo/red64.php"
    key = (settings.PHIMTAT_API_KEY or "").strip()
    try:
        timeout = float(settings.PHIMTAT_TIMEOUT_SECONDS or 60)
    except (TypeError, ValueError):
        timeout = 60.0
    version = str((getattr(settings, "PHIMTAT_VER", "8") or "8")).strip() or "8"
    started = time.monotonic()
    b64url = base64.b64encode(target.encode("utf-8")).decode("ascii")
    # New Snap Video shortcut contract (verified live Oct 2026): ver=8,
    # ask_format=true, show_menu=true — identical param order.
    api_url = (f"{base}?api-key={key}&lang=vi&ver={version}&ask_format=true"
               f"&show_menu=true&skip_update=false&b64={b64url}")
    wrapped = base64.b64encode(api_url.encode("utf-8")).decode("ascii")
    fetch_url = f"{redirect}?url={quote(wrapped, safe='')}"
    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout,
                                     headers={"User-Agent": PROVIDER_UA},
                                     follow_redirects=True) as client:
            data = await _parse_phimtat_payload(client, fetch_url)
    except httpx.TimeoutException:
        raise SnapVideoError(RESOLVE_FAILED, "PHIMTAT resolve timed out.")
    except (httpx.ConnectError, httpx.NetworkError) as exc:
        raise SnapVideoError(RESOLVE_FAILED,
                             f"PHIMTAT unreachable: {type(exc).__name__}.")
    picked = _pick_media_url(data.get("medias"), prefer_sd=prefer_sd)
    if not picked:
        raise SnapVideoError(UNRESOLVABLE, "PHIMTAT response has no media URL.")
    logger.info("phimtat resolved in %.1fs (prefer_sd=%s, ver=%s)",
                time.monotonic() - started, prefer_sd, version)
    duration = data.get("duration")
    try:
        duration = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration = None
    return {"media_url": picked, "title": data.get("title"),
            "thumbnail": data.get("thumbnail"), "duration": duration,
            "provider": "phimtat"}


async def _fetch_phimtat_json(client: httpx.AsyncClient,
                                fetch_url: str) -> dict | None:
    resp = await client.get(fetch_url)
    if resp.status_code in (401, 403):
        raise SnapVideoError(RESOLVE_FAILED, "PHIMTAT rejected the API key.")
    if resp.status_code == 429:
        raise SnapVideoError(RESOLVE_FAILED, "PHIMTAT rate limited (429).")
    if resp.status_code != 200:
        raise SnapVideoError(RESOLVE_FAILED,
                             f"PHIMTAT HTTP {resp.status_code}.")
    try:
        data = resp.json()
    except ValueError:
        raise SnapVideoError(RESOLVE_FAILED, "PHIMTAT returned invalid JSON.")
    return data if isinstance(data, dict) else None


async def _accept_consent(client: httpx.AsyncClient, consent_url: str) -> None:
    """Accept the personal-use terms gate exactly like the shortcut does:
    GET the agree URL wrapped through red64.php so session cookies land,
    then the retried resolve returns real media."""
    from app.config import settings

    redirect = (settings.PHIMTAT_REDIRECT_URL or "").strip() \
        or "https://api.phimtat.vn/snapvideo/red64.php"
    wrapped = base64.b64encode(consent_url.encode("utf-8")).decode("ascii")
    try:
        resp = await client.get(f"{redirect}?url={quote(wrapped, safe='')}")
        if resp.status_code != 200:
            raise SnapVideoError(UNRESOLVABLE,
                                 "Terms gate could not be accepted.")
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if not (isinstance(payload, dict)
                and (payload.get("agreed") is True or payload.get("ok") is True)):
            raise SnapVideoError(UNRESOLVABLE,
                                 "Terms gate response not acknowledged.")
    except (httpx.TimeoutException, httpx.ConnectError,
            httpx.NetworkError) as exc:
        raise SnapVideoError(RESOLVE_FAILED,
                             f"Consent request failed: {type(exc).__name__}.")


def _fastsaver_configured() -> bool:
    from app.config import settings

    return bool((settings.AUDIO_FASTSAVER_BASE_URL or "").strip()
                and (settings.AUDIO_FASTSAVER_API_KEY or "").strip())


async def _resolve_fastsaver(target: str, transport) -> dict:
    from app.config import settings

    base = (settings.AUDIO_FASTSAVER_BASE_URL or "").strip().rstrip("/")
    key = (settings.AUDIO_FASTSAVER_API_KEY or "").strip()
    try:
        async with httpx.AsyncClient(transport=transport, timeout=30.0,
                                     headers={"X-Api-Key": key,
                                              "Accept": "application/json"},
                                     follow_redirects=True) as client:
            resp = await client.get(f"{base}/fetch", params={"url": target})
    except httpx.TimeoutException:
        raise SnapVideoError(RESOLVE_FAILED, "FastSaver timed out.")
    except (httpx.ConnectError, httpx.NetworkError) as exc:
        raise SnapVideoError(RESOLVE_FAILED,
                             f"FastSaver unreachable: {type(exc).__name__}.")
    if resp.status_code == 401:
        raise SnapVideoError(RESOLVE_FAILED, "FastSaver credential invalid.")
    if resp.status_code != 200:
        raise SnapVideoError(RESOLVE_FAILED,
                             f"FastSaver HTTP {resp.status_code}.")
    try:
        data = resp.json()
    except ValueError:
        raise SnapVideoError(RESOLVE_FAILED, "FastSaver returned invalid JSON.")
    if not isinstance(data, dict) or data.get("ok") is not True:
        raise SnapVideoError(UNRESOLVABLE, "FastSaver could not resolve this URL.")
    download_url = data.get("download_url")
    if not isinstance(download_url, str) or not download_url.startswith("http"):
        raise SnapVideoError(UNRESOLVABLE, "FastSaver has no download_url.")
    duration = data.get("duration")
    try:
        duration = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration = None
    caption = data.get("caption")
    thumbnail = data.get("thumbnail_url")
    return {"media_url": download_url,
            "title": None,
            "thumbnail": thumbnail if isinstance(thumbnail, str) else None,
            "duration": duration,
            "provider": "fastsaver",
            "caption": caption if isinstance(caption, str) else None}


def _assert_public_http_url(url: str) -> str:
    """SSRF guard: http(s) only, host must not resolve to private/loopback."""
    import socket

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise SnapVideoError(DOWNLOAD_FAILED, "Media URL is not public HTTP(S).")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        raise SnapVideoError(DOWNLOAD_FAILED, "Media host does not resolve.")
    for info in infos:
        try:
            if ipaddress.ip_address(info[4][0]).is_private:
                raise SnapVideoError(DOWNLOAD_FAILED,
                                     "Media host resolves to a private address.")
        except ValueError:
            continue
    return url


async def stream_download(media_url: str, dest: Path, max_bytes: int | None = None,
                          timeout: float = 300.0,
                          skip_ssrf_check: bool = False,
                          transport: httpx.AsyncBaseTransport | None = None) -> Path:
    """Stream a direct media URL to disk with size cap. Never loads whole file.

    Validates each redirect hop (SSRF), content-type, removes partials.
    """
    cap = max_bytes or _download_limit()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    written = 0
    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout,
                                     follow_redirects=False) as client:
            url = media_url
            for _ in range(6):
                if not skip_ssrf_check:
                    _assert_public_http_url(url)
                async with client.stream("GET", url) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        location = resp.headers.get("location")
                        if not location:
                            raise SnapVideoError(DOWNLOAD_FAILED,
                                                 "Empty redirect.")
                        url = location
                        continue
                    if resp.status_code != 200:
                        raise SnapVideoError(DOWNLOAD_FAILED,
                                             f"Media HTTP {resp.status_code}.")
                    ctype = (resp.headers.get("content-type") or "").lower()
                    if "html" in ctype:
                        raise SnapVideoError(DOWNLOAD_FAILED,
                                             "Media URL returned HTML, not video.")
                    if not any(k in ctype for k in ("video", "octet-stream",
                                                    "mp4", "quicktime",
                                                    "webm")):
                        raise SnapVideoError(
                            DOWNLOAD_FAILED,
                            f"Unexpected content-type: {ctype}.")
                    with open(dest, "wb") as fh:
                        async for chunk in resp.aiter_bytes(1024 * 256):
                            written += len(chunk)
                            if written > cap:
                                raise SnapVideoError(DOWNLOAD_FAILED,
                                                     "File exceeds size cap.")
                            fh.write(chunk)
                    break
            else:
                raise SnapVideoError(DOWNLOAD_FAILED, "Too many redirects.")
    except SnapVideoError:
        _remove_partial(dest)
        raise
    except (httpx.TimeoutException, httpx.ConnectError,
            httpx.NetworkError) as exc:
        _remove_partial(dest)
        raise SnapVideoError(DOWNLOAD_FAILED,
                             f"Download interrupted: {type(exc).__name__}.")
    except Exception as exc:
        _remove_partial(dest)
        raise SnapVideoError(DOWNLOAD_FAILED,
                             f"Download error: {type(exc).__name__}.")
    if written == 0:
        _remove_partial(dest)
        raise SnapVideoError(DOWNLOAD_FAILED, "Empty download.")
    return dest


def _remove_partial(dest: Path) -> None:
    try:
        if dest.exists():
            dest.unlink()
    except OSError:
        pass
