"""Facebook media resolver + stream downloader (Task 6B).

Primary resolver: FastSaver (GET {base}/fetch?url=... with X-Api-Key).
The signed download_url is short-lived: resolve and download in the SAME job,
never persist it to Turso. The API key never appears in logs or exceptions.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

from .facebook_url import is_facebook_url

logger = logging.getLogger("backend-facebook.media")

# Stable error codes (no secrets in messages).
AUTH_ERROR = "FASTSAVER_AUTH_ERROR"
RATE_LIMITED = "FASTSAVER_RATE_LIMITED"
RESOLVE_FAILED = "FASTSAVER_RESOLVE_FAILED"
UPSTREAM_ERROR = "FASTSAVER_UPSTREAM_ERROR"
TIMEOUT = "FASTSAVER_TIMEOUT"
RESPONSE_INVALID = "FASTSAVER_RESPONSE_INVALID"
DOWNLOAD_FAILED = "MEDIA_DOWNLOAD_FAILED"
TOO_LARGE = "MEDIA_TOO_LARGE"
BAD_CONTENT_TYPE = "MEDIA_BAD_CONTENT_TYPE"

CHUNK_SIZE = 1024 * 1024  # 1 MiB, never load the whole file into RAM.
TMP_ROOT = Path("/tmp/facebook")

_JOB_ID_RE = re.compile(r"[^A-Za-z0-9_-]")


class FacebookMediaError(Exception):
    """Typed resolver/downloader error. Never carries the API key."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class ResolvedFacebookMedia:
    download_url: str
    source: str
    media_type: str
    thumbnail_url: str | None
    duration: float | None
    caption: str | None


@dataclass
class MediaResolverConfig:
    base_url: str
    api_key: str
    resolver_timeout: float = 60.0
    max_bytes: int = 1_000_000_000  # 1 GB default guard.


def sanitize_job_id(job_id: str | None) -> str:
    """Internal job ids only: strip traversal/unsafe chars, or generate one."""
    if not job_id:
        return f"job_{uuid.uuid4().hex[:12]}"
    cleaned = _JOB_ID_RE.sub("", job_id)
    if not cleaned:
        raise FacebookMediaError(DOWNLOAD_FAILED, "Invalid job_id.")
    return cleaned


def job_dir(job_id: str, tmp_root: Path = TMP_ROOT) -> Path:
    safe = sanitize_job_id(job_id)
    path = tmp_root / safe
    # Traversal-proof: resolved path must stay inside tmp_root.
    if tmp_root.resolve() not in path.resolve().parents and path.resolve() != tmp_root.resolve():
        raise FacebookMediaError(DOWNLOAD_FAILED, "Invalid job path.")
    return path


def cleanup_job_dir(path: Path) -> None:
    """Best-effort removal of a job directory (partial files included)."""
    try:
        if path.is_file():
            path.unlink(missing_ok=True)
            return
        if path.is_dir():
            for child in path.iterdir():
                if child.is_file() or child.is_symlink():
                    child.unlink(missing_ok=True)
            path.rmdir()
    except OSError as exc:
        logger.warning("cleanup failed for %s: %s", path, exc)


class FacebookMediaResolver:
    """FastSaver-backed resolver. One instance per job; client reused inside."""

    def __init__(
        self,
        config: MediaResolverConfig,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not config.api_key:
            raise FacebookMediaError(AUTH_ERROR, "FASTSAVER_API_KEY is not configured.")
        self.config = config
        self._transport = transport

    @classmethod
    def from_settings(cls, transport: httpx.AsyncBaseTransport | None = None) -> "FacebookMediaResolver":
        from ..config import settings

        base_url, api_key = settings.require_fastsaver()
        return cls(
            MediaResolverConfig(
                base_url=base_url,
                api_key=api_key,
                resolver_timeout=settings.FASTSAVER_TIMEOUT,
                max_bytes=settings.FACEBOOK_MEDIA_MAX_BYTES,
            ),
            transport=transport,
        )

    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self.config.api_key, "Accept": "application/json"}

    def _client(self, timeout: httpx.Timeout | float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            base_url=self.config.base_url,
            timeout=timeout,
            headers=self._headers(),
            follow_redirects=True,
        )

    async def resolve(self, reel_url: str) -> ResolvedFacebookMedia:
        """reel_url -> short-lived direct download_url. Raises FacebookMediaError."""
        if not reel_url or not is_facebook_url(reel_url):
            raise FacebookMediaError(RESOLVE_FAILED, "Not a valid Facebook URL.")
        try:
            async with self._client(self.config.resolver_timeout) as client:
                resp = await client.get("/fetch", params={"url": reel_url.strip()})
        except httpx.TimeoutException:
            raise FacebookMediaError(TIMEOUT, "FastSaver resolve timed out.")
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise FacebookMediaError(UPSTREAM_ERROR, f"FastSaver unreachable: {type(exc).__name__}.")

        if resp.status_code == 401:
            raise FacebookMediaError(AUTH_ERROR, "FastSaver credential invalid (401).")
        if resp.status_code == 429:
            raise FacebookMediaError(RATE_LIMITED, "FastSaver rate limited (429).")
        if 500 <= resp.status_code <= 599:
            raise FacebookMediaError(UPSTREAM_ERROR, f"FastSaver provider error ({resp.status_code}).")
        if resp.status_code != 200:
            raise FacebookMediaError(RESOLVE_FAILED, f"FastSaver resolve failed ({resp.status_code}).")

        try:
            data = resp.json()
        except ValueError:
            raise FacebookMediaError(RESPONSE_INVALID, "FastSaver returned invalid JSON.")
        if not isinstance(data, dict):
            raise FacebookMediaError(RESPONSE_INVALID, "FastSaver response is not an object.")
        if data.get("ok") is not True:
            raise FacebookMediaError(RESOLVE_FAILED, "FastSaver could not resolve this URL.")

        download_url = data.get("download_url")
        if not download_url or not isinstance(download_url, str):
            raise FacebookMediaError(RESPONSE_INVALID, "FastSaver response has no download_url.")
        media_type = str(data.get("type") or "video")
        if media_type != "video":
            raise FacebookMediaError(RESPONSE_INVALID, f"Unsupported media type: {media_type}.")
        source = str(data.get("source") or "")
        if source and "facebook" not in source.lower() and "fb" not in source.lower():
            logger.warning("unexpected FastSaver source: %s", source[:60])

        duration = data.get("duration")
        try:
            duration = float(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration = None
        thumbnail = data.get("thumbnail_url")
        caption = data.get("caption")
        return ResolvedFacebookMedia(
            download_url=download_url,
            source=source,
            media_type=media_type,
            thumbnail_url=thumbnail if isinstance(thumbnail, str) else None,
            duration=duration,
            caption=caption if isinstance(caption, str) else None,
        )

    async def get_balance(self) -> dict:
        """Smoke-test only: never call per reel."""
        try:
            async with self._client(30.0) as client:
                resp = await client.get("/balance")
        except httpx.TimeoutException:
            raise FacebookMediaError(TIMEOUT, "FastSaver balance check timed out.")
        except (httpx.ConnectError, httpx.NetworkError):
            raise FacebookMediaError(UPSTREAM_ERROR, "FastSaver unreachable.")
        if resp.status_code == 401:
            raise FacebookMediaError(AUTH_ERROR, "FastSaver credential invalid (401).")
        if resp.status_code != 200:
            raise FacebookMediaError(UPSTREAM_ERROR, f"FastSaver balance failed ({resp.status_code}).")
        try:
            data = resp.json()
        except ValueError:
            raise FacebookMediaError(RESPONSE_INVALID, "FastSaver balance returned invalid JSON.")
        return data if isinstance(data, dict) else {"value": data}

    async def download_media(
        self,
        media: ResolvedFacebookMedia,
        job_id: str,
        tmp_root: Path = TMP_ROOT,
    ) -> Path:
        """Stream download_url -> /tmp/facebook/<job_id>/video.mp4 (chunked, guarded)."""
        target_dir = job_dir(job_id, tmp_root)
        target_dir.mkdir(parents=True, exist_ok=True)
        output = target_dir / "video.mp4"
        if output.exists():
            output.unlink()

        timeout = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=30.0)
        received = 0
        try:
            async with self._client(timeout) as client:
                async with client.stream("GET", media.download_url) as resp:
                    if resp.status_code != 200:
                        raise FacebookMediaError(
                            DOWNLOAD_FAILED, f"Media download failed ({resp.status_code})."
                        )
                    content_type = (resp.headers.get("Content-Type", "") or "").lower().split(";")[0].strip()
                    if content_type and (
                        not content_type.startswith("video/") and content_type != "application/octet-stream"
                    ):
                        raise FacebookMediaError(
                            BAD_CONTENT_TYPE, f"Unexpected media Content-Type: {content_type or 'missing'}."
                        )
                    declared = resp.headers.get("Content-Length")
                    if declared is not None:
                        try:
                            if int(declared) > self.config.max_bytes:
                                raise FacebookMediaError(
                                    TOO_LARGE, "Media exceeds configured max size."
                                )
                        except ValueError:
                            pass
                    with output.open("wb") as fh:
                        async for chunk in resp.aiter_bytes(CHUNK_SIZE):
                            if not chunk:
                                continue
                            received += len(chunk)
                            if received > self.config.max_bytes:
                                raise FacebookMediaError(TOO_LARGE, "Media exceeds configured max size.")
                            fh.write(chunk)
        except FacebookMediaError:
            cleanup_job_dir(target_dir)
            raise
        except httpx.TimeoutException:
            cleanup_job_dir(target_dir)
            raise FacebookMediaError(TIMEOUT, "Media download timed out.")
        except (httpx.ConnectError, httpx.NetworkError, OSError) as exc:
            cleanup_job_dir(target_dir)
            raise FacebookMediaError(DOWNLOAD_FAILED, f"Media download interrupted: {type(exc).__name__}.")

        if not output.exists() or output.stat().st_size == 0:
            cleanup_job_dir(target_dir)
            raise FacebookMediaError(DOWNLOAD_FAILED, "Downloaded file is empty.")
        return output
