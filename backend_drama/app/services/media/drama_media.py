"""Drama episode media resolver and stream downloader.

Resolver priority:
1. DIRECT_MP4: Direct MP4 file URL from episode metadata.
2. HLS: HTTP Live Streaming (.m3u8) playlist URL from episode or web schema.
3. PHIMTAT: SnapVideo/PHIMTAT external resolver flow.
4. MEDIA_UNAVAILABLE: Raised when no media can be resolved.
"""

import asyncio
import base64
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
import subprocess
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from ...config import settings

logger = logging.getLogger("backend-drama-media")

MAX_BYTES = 1_000_000_000  # 1GB guard
CHUNK_SIZE = 1024 * 256     # 256KB chunks
DEFAULT_TIMEOUT_SECONDS = 120.0

PROVIDER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

# Preferred media label for SnapVideo/PHIMTAT
MP4_HD_LABEL = "🎬 MP4 HD"
_SKIP_LABEL_HINTS = ("close", "guide", "update", "{{open-url}}")

# Typed error codes
MEDIA_UNAVAILABLE = "MEDIA_UNAVAILABLE"
SNAPVIDEO_UNSUPPORTED = "SNAPVIDEO_UNSUPPORTED"
DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
AUTH_FAILED = "AUTH_FAILED"
TIMEOUT = "TIMEOUT"
RATE_LIMITED = "RATE_LIMITED"
INVALID_RESPONSE = "INVALID_RESPONSE"


class DramaMediaError(Exception):
    """Typed error for drama media resolution and download.

    Never exposes API keys or signed query parameters.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class ResolvedDramaMedia:
    media_url: str          # Internal direct stream/file URL
    media_type: str         # "DIRECT_MP4" | "HLS" | "PHIMTAT"
    download_host: str      # Safe hostname only
    duration: float | None = None
    label: str | None = None
    source_title: str | None = None


def is_supported_drama_url(raw_url: str | None) -> bool:
    """Validate that the URL belongs to a recognized web video / drama source."""
    if not isinstance(raw_url, str) or not raw_url.strip():
        return False
    try:
        p = urlparse(raw_url.strip())
        if p.scheme.lower() not in ("http", "https"):
            return False
        return bool(p.netloc)
    except Exception:
        return False


def _pick_phimtat_media_url(medias: Any) -> tuple[str | None, str | None]:
    """Select best media URL from PHIMTAT medias dictionary.

    Returns (url, label).
    """
    if not isinstance(medias, dict):
        return None, None

    # Priority 1: Exact MP4_HD_LABEL
    for label, url in medias.items():
        if not isinstance(url, str) or not url.strip():
            continue
        u = url.strip()
        if not u.lower().startswith(("http://", "https://")):
            continue
        if "{{open-url}}" in u.lower():
            continue
        if str(label).strip() == MP4_HD_LABEL:
            return u, str(label).strip()

    # Priority 2: Direct mp4 extension or mp4 in label
    first_candidate: tuple[str, str] | None = None
    for label, url in medias.items():
        if not isinstance(url, str) or not url.strip():
            continue
        u = url.strip()
        if not u.lower().startswith(("http://", "https://")):
            continue
        lowered_label = str(label or "").lower()
        if any(hint in lowered_label for hint in _SKIP_LABEL_HINTS):
            continue
        if "{{open-url}}" in u.lower():
            continue
        if ".mp4" in u.lower() or "mp4" in lowered_label:
            return u, str(label).strip()
        if first_candidate is None:
            first_candidate = (u, str(label).strip())

    return first_candidate if first_candidate is not None else (None, None)


async def resolve_via_phimtat(target_url: str, client: httpx.AsyncClient | None = None) -> ResolvedDramaMedia:
    """Execute SnapVideo/PHIMTAT resolver workflow."""
    api_base = (settings.PHIMTAT_API_BASE_URL or "").strip()
    redirect_url = (settings.PHIMTAT_REDIRECT_URL or "").strip()
    api_key = settings.phimtat_api_key()
    timeout = settings.phimtat_timeout()

    if not api_base or not redirect_url or not api_key:
        raise DramaMediaError(AUTH_FAILED, "PHIMTAT endpoints or API key not configured.")

    if not is_supported_drama_url(target_url):
        raise DramaMediaError(SNAPVIDEO_UNSUPPORTED, "Unsupported Drama URL format.")

    b64url = base64.b64encode(target_url.strip().encode("utf-8")).decode("ascii")
    api_url = (
        f"{api_base}"
        f"?api-key={api_key}&lang=vi&ver=7"
        f"&ask_format=false&show_menu=false&skip_update=false"
        f"&b64={b64url}"
    )
    wrapped = base64.b64encode(api_url.encode("utf-8")).decode("ascii")
    fetch_url = f"{redirect_url}?url={quote(wrapped, safe='')}"

    headers = {"User-Agent": PROVIDER_UA}
    should_close = False
    if client is None:
        client = httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True)
        should_close = True

    try:
        resp = await client.get(fetch_url)
    except httpx.TimeoutException:
        raise DramaMediaError(TIMEOUT, "PHIMTAT resolver request timed out.")
    except Exception as exc:
        raise DramaMediaError(SNAPVIDEO_UNSUPPORTED, f"PHIMTAT request failed: {type(exc).__name__}")
    finally:
        if should_close:
            await client.aclose()

    if resp.status_code in (401, 403):
        raise DramaMediaError(AUTH_FAILED, "PHIMTAT rejected API key.")
    if resp.status_code == 429:
        raise DramaMediaError(RATE_LIMITED, "PHIMTAT rate limit reached.")

    try:
        data = resp.json()
    except Exception:
        raise DramaMediaError(INVALID_RESPONSE, f"PHIMTAT returned non-JSON response ({resp.status_code}).")

    if resp.status_code != 200:
        menu_title = data.get("menu_title") or "Platform not supported"
        raise DramaMediaError(SNAPVIDEO_UNSUPPORTED, f"{menu_title} (HTTP {resp.status_code})")

    media_url, label = _pick_phimtat_media_url(data.get("medias"))
    if not media_url:
        menu_title = data.get("menu_title") or "Nền tảng chưa được hỗ trợ"
        raise DramaMediaError(SNAPVIDEO_UNSUPPORTED, f"{menu_title} (HTTP 400)")

    parsed_host = urlparse(media_url).netloc
    return ResolvedDramaMedia(
        media_url=media_url,
        media_type="PHIMTAT",
        download_host=parsed_host,
        label=label,
        source_title=data.get("title"),
    )


async def extract_webpage_hls(url: str, client: httpx.AsyncClient | None = None) -> str | None:
    """Extract direct HLS (.m3u8) stream from webpage LD+JSON metadata."""
    headers = {"User-Agent": PROVIDER_UA}
    should_close = False
    if client is None:
        client = httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True)
        should_close = True

    try:
        resp = await client.get(url)
        if resp.status_code != 200:
            return None
        text = resp.text

        # 1. Search for contentUrl in ld+json
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', text, re.DOTALL)
        if m:
            pass  # usually __NEXT_DATA__ doesn't have video URL for non-VIP, checked above

        # Check ld+json scripts
        for script_match in re.finditer(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', text, re.DOTALL):
            try:
                ld_data = json.loads(script_match.group(1))
                if isinstance(ld_data, dict):
                    cu = ld_data.get("contentUrl")
                    if isinstance(cu, str) and ".m3u8" in cu.lower():
                        return cu
            except Exception:
                continue

        # Direct regex search for m3u8 in full HTML
        matches = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', text)
        if matches:
            return matches[0]

        return None
    except Exception as exc:
        logger.warning("Failed to extract webpage HLS from %s: %s", url, exc)
        return None
    finally:
        if should_close:
            await client.aclose()


async def resolve_drama_media(
    *,
    source_url: str | None = None,
    raw_payload: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
) -> ResolvedDramaMedia:
    """Resolve episode media according to strict priority:

    1. DIRECT_MP4
    2. HLS (.m3u8)
    3. PHIMTAT (SnapVideo)
    4. MEDIA_UNAVAILABLE
    """
    raw = raw_payload or {}

    # Priority 1: DIRECT_MP4
    candidate_urls: list[str] = []
    for k in ("video_url", "play_url", "playUrl", "stream_url", "streamUrl", "mp4_url", "file", "url", "video"):
        val = raw.get(k)
        if isinstance(val, str) and val.strip().lower().startswith(("http://", "https://")):
            candidate_urls.append(val.strip())

    if source_url and source_url.strip().lower().startswith(("http://", "https://")):
        candidate_urls.append(source_url.strip())

    for u in candidate_urls:
        if ".mp4" in u.lower():
            p = urlparse(u)
            return ResolvedDramaMedia(
                media_url=u,
                media_type="DIRECT_MP4",
                download_host=p.netloc,
            )

    # Priority 2: HLS (.m3u8)
    for u in candidate_urls:
        if ".m3u8" in u.lower():
            p = urlparse(u)
            return ResolvedDramaMedia(
                media_url=u,
                media_type="HLS",
                download_host=p.netloc,
            )

    # If source_url is a webpage, attempt extracting HLS from web schema (e.g. ReelShort)
    if source_url and is_supported_drama_url(source_url):
        web_hls = await extract_webpage_hls(source_url, client=client)
        if web_hls:
            p = urlparse(web_hls)
            return ResolvedDramaMedia(
                media_url=web_hls,
                media_type="HLS",
                download_host=p.netloc,
            )

    # Priority 3: PHIMTAT / SnapVideo fallback
    if settings.PHIMTAT_ENABLED and settings.phimtat_api_key() and source_url:
        try:
            return await resolve_via_phimtat(source_url, client=client)
        except DramaMediaError as exc:
            logger.info("PHIMTAT fallback unsuccessful: %s (%s)", exc, exc.code)
            # Re-raise SNAPVIDEO_UNSUPPORTED or continue to MEDIA_UNAVAILABLE

    # Priority 4: MEDIA_UNAVAILABLE
    raise DramaMediaError(
        MEDIA_UNAVAILABLE,
        "Không thể tìm thấy nguồn video (Direct MP4, HLS, hoặc PHIMTAT đều không khả dụng).",
    )


def download_resolved_media(
    media: ResolvedDramaMedia,
    target_file: Path,
    *,
    max_bytes: int = MAX_BYTES,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> Path:
    """Stream download or remux resolved media to target MP4 file.

    Chunked streaming. No in-memory buffering. File size guard. Timeout.
    """
    target_file.parent.mkdir(parents=True, exist_ok=True)
    if target_file.exists():
        target_file.unlink()

    if media.media_type in ("DIRECT_MP4", "PHIMTAT"):
        # HTTP chunked stream download
        timeout = httpx.Timeout(connect=15.0, read=timeout_seconds, write=30.0, pool=30.0)
        received = 0
        headers = {"User-Agent": PROVIDER_UA}
        try:
            with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
                with client.stream("GET", media.media_url) as resp:
                    if resp.status_code != 200:
                        raise DramaMediaError(
                            DOWNLOAD_FAILED, f"Download failed with HTTP status {resp.status_code}"
                        )
                    ct = (resp.headers.get("Content-Type", "") or "").lower().split(";")[0].strip()
                    if ct and not ct.startswith("video/") and ct != "application/octet-stream":
                        raise DramaMediaError(
                            DOWNLOAD_FAILED, f"Unexpected Content-Type: {ct}"
                        )
                    with target_file.open("wb") as fh:
                        for chunk in resp.iter_bytes(CHUNK_SIZE):
                            if not chunk:
                                continue
                            received += len(chunk)
                            if received > max_bytes:
                                raise DramaMediaError(DOWNLOAD_FAILED, "Media exceeds maximum size guard.")
                            fh.write(chunk)
        except DramaMediaError:
            if target_file.exists():
                target_file.unlink()
            raise
        except Exception as exc:
            if target_file.exists():
                target_file.unlink()
            raise DramaMediaError(DOWNLOAD_FAILED, f"Download failed: {exc}")

        if received <= 0 or not target_file.exists() or target_file.stat().st_size <= 0:
            if target_file.exists():
                target_file.unlink()
            raise DramaMediaError(DOWNLOAD_FAILED, "Downloaded file is empty.")

        return target_file

    elif media.media_type == "HLS":
        # HLS stream remuxing via ffmpeg
        cmd = [
            "ffmpeg", "-y",
            "-timeout", str(int(timeout_seconds * 1_000_000)),
            "-i", media.media_url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            str(target_file),
        ]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_seconds)
            if proc.returncode != 0:
                if target_file.exists():
                    target_file.unlink()
                err_msg = proc.stderr.decode("utf-8", errors="ignore")[-200:]
                raise DramaMediaError(DOWNLOAD_FAILED, f"FFmpeg HLS download failed: {err_msg}")
        except subprocess.TimeoutExpired:
            if target_file.exists():
                target_file.unlink()
            raise DramaMediaError(TIMEOUT, "FFmpeg HLS download timed out.")
        except Exception as exc:
            if target_file.exists():
                target_file.unlink()
            raise DramaMediaError(DOWNLOAD_FAILED, f"FFmpeg error: {exc}")

        if not target_file.exists() or target_file.stat().st_size <= 0:
            if target_file.exists():
                target_file.unlink()
            raise DramaMediaError(DOWNLOAD_FAILED, "Downloaded HLS file is empty.")

        if target_file.stat().st_size > max_bytes:
            target_file.unlink()
            raise DramaMediaError(DOWNLOAD_FAILED, "HLS file exceeds max size guard.")

        return target_file

    else:
        raise DramaMediaError(MEDIA_UNAVAILABLE, f"Unsupported media type: {media.media_type}")


def probe_media(file_path: Path) -> dict[str, Any]:
    """Run ffprobe to inspect video duration, codec, width, height."""
    if not file_path.exists():
        raise FileNotFoundError(f"Media file not found: {file_path}")

    file_bytes = file_path.stat().st_size
    probe_cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(file_path),
    ]
    res = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
    data = json.loads(res.stdout)
    fmt = data.get("format", {})
    duration = float(fmt.get("duration", 0.0))

    codec = "unknown"
    width = 0
    height = 0
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            codec = s.get("codec_name", "unknown")
            width = int(s.get("width", 0))
            height = int(s.get("height", 0))
            break

    return {
        "file_bytes": file_bytes,
        "duration": duration,
        "codec": codec,
        "width": width,
        "height": height,
        "resolution": f"{width}x{height}",
    }
