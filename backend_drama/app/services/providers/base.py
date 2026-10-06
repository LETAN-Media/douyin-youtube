"""Multi-provider drama adapters (Short Drama Pro hub + legacy rapidix).

Every provider speaks through DramaProvider and returns the SAME normalized
models, so the scanner never branches on provider names. Provider-specifics
(paths, params, id fields) live in exactly one file each.
"""

import abc
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger("backend-drama-providers")

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RETRY_BACKOFF_SECONDS = (1.0, 2.0, 4.0)
MAX_ATTEMPTS = len(RETRY_BACKOFF_SECONDS) + 1


class ProviderError(Exception):
    """Typed provider error. Never carries API keys or signed URLs."""

    def __init__(self, code: str, message: str, retry_after: float | None = None,
                 http_status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after
        self.http_status = http_status


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: ("<redacted>" if "key" in str(k).lower() else _redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [_redact(v) for v in obj]
    return obj


def _parse_retry_after(value: str | None) -> float | None:
    """Retry-After seconds (delta or HTTP date). None when absent/unparseable."""
    if not value:
        return None
    try:
        seconds = float(str(value).strip())
        if seconds >= 0:
            return seconds
    except (TypeError, ValueError):
        pass
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(str(value).strip())
        import datetime as _dt

        delta = (dt - _dt.datetime.now(_dt.timezone.utc)).total_seconds()
        return max(0.0, delta)
    except Exception:
        return None


def mask_url(url: str) -> str:
    """Hostname + path shape only — never query/signature material."""
    try:
        from urllib.parse import urlparse

        p = urlparse(url)
        host = p.hostname or "?"
        return f"{host}{p.path}"
    except Exception:
        return "?"


_VIDEO_URL_KEYS = (
    "video_url", "play_url", "playUrl", "stream_url", "streamUrl",
    "hls_url", "hls", "m3u8", "m3u8_url", "mp4_url", "file", "url",
    "video", "source", "embed_url", "player_url",
)


@dataclass
class ResolvedEpisodeMedia:
    """What a provider knows about playable media (Phase 1: informational).

    Signed URLs are never persisted as identity and never returned raw;
    only hostname/field presence is reported.
    """

    provider: str
    external_episode_id: str
    video_url: str | None = None
    video_type: str | None = None  # "mp4" | "hls" | "embed" | None
    expires: str | None = None
    has_subtitle: bool = False
    has_audio: bool = False
    thumbnail_url: str | None = None
    duration: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

def extract_media(provider: str, external_episode_id: str, raw: dict) -> ResolvedEpisodeMedia:
    """Best-effort playable-media summary from a provider episode payload.

    Never raises on odd shapes; reports presence/hostname only.
    """
    video_url: str | None = None
    video_type: str | None = None
    if isinstance(raw, dict):
        for key in _VIDEO_URL_KEYS:
            value = raw.get(key)
            if isinstance(value, str) and value.lower().startswith(("http://", "https://")):
                video_url = value
                lowered = value.lower()
                if ".m3u8" in lowered:
                    video_type = "hls"
                elif ".mp4" in lowered:
                    video_type = "mp4"
                elif "embed" in key.lower():
                    video_type = "embed"
                break
        expires = None
        for key in ("expires", "expire", "expiry", "expires_at", "expire_at"):
            if raw.get(key) is not None:
                expires = str(raw.get(key))
                break
        blob = " ".join(str(k) for k in raw.keys()).lower()
        has_subtitle = any(k in blob for k in ("subtitle", "caption", "srt", "vtt"))
        has_audio = any(k in blob for k in ("audio", "sound", "track", "voice"))
        duration = None
        for key in ("duration", "duration_seconds", "length"):
            try:
                if raw.get(key) is not None:
                    duration = float(str(raw.get(key)))
                    break
            except (TypeError, ValueError):
                continue
        thumbnail = None
        for key in ("thumbnail_url", "thumbnail", "cover", "cover_url", "image"):
            if isinstance(raw.get(key), str):
                thumbnail = raw.get(key)
                break
    else:
        expires, has_subtitle, has_audio, duration, thumbnail = None, False, False, None, None
    return ResolvedEpisodeMedia(
        provider=provider,
        external_episode_id=external_episode_id,
        video_url=video_url,
        video_type=video_type,
        expires=expires,
        has_subtitle=has_subtitle,
        has_audio=has_audio,
        thumbnail_url=thumbnail,
        duration=duration,
        raw=raw if isinstance(raw, dict) else {},
    )


class RapidApiProvider:
    """Shared RapidAPI GET machinery (key/host headers, typed retries)."""

    def __init__(
        self,
        *,
        base_url: str,
        host: str,
        api_key: str,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not (base_url or "").strip():
            raise ProviderError("NOT_CONFIGURED", "Provider base URL is not configured.")
        if not (host or "").strip():
            raise ProviderError("NOT_CONFIGURED", "Provider host is not configured.")
        if not (api_key or "").strip():
            raise ProviderError("NOT_CONFIGURED", "Provider API key is not configured.")
        self.base_url = base_url.strip().rstrip("/")
        self.host = host.strip()
        self._api_key = api_key.strip()
        self.timeout = timeout_seconds
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        # RapidAPI gateway auth uses THESE headers (not x-api-key).
        return {"x-rapidapi-key": self._api_key, "x-rapidapi-host": self.host}

    async def _get(self, path: str, params: dict | None = None) -> Any:
        last_error = "unknown"
        code = "TEMPORARY"
        retry_after: float | None = None
        last_http: int | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                async with httpx.AsyncClient(
                    transport=self._transport,
                    base_url=self.base_url,
                    timeout=self.timeout,
                    headers=self._headers(),
                ) as client:
                    resp = await client.get(path, params=params or {})
            except httpx.TimeoutException:
                last_error, code = "timeout", "TIMEOUT"
            except (httpx.ConnectError, httpx.NetworkError):
                last_error, code = "unreachable", "TEMPORARY"
            else:
                last_http = resp.status_code
                if resp.status_code == 429:
                    last_error, code = "rate limited (429)", "RATE_LIMITED"
                    retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                elif resp.status_code == 404:
                    raise ProviderError("NOT_FOUND", "Provider has no such resource.",
                                        http_status=404)
                elif resp.status_code == 403:
                    raise ProviderError(
                        "SUBSCRIPTION_ERROR",
                        "Provider refused the request (not subscribed).",
                        http_status=403,
                    )
                elif resp.status_code in (401,):
                    raise ProviderError("AUTH_FAILED", "Provider rejected the API key.",
                                        http_status=401)
                elif resp.status_code in (500, 502, 503, 504):
                    last_error, code = f"server error ({resp.status_code})", "TEMPORARY"
                elif resp.status_code != 200:
                    raise ProviderError(
                        "INVALID_RESPONSE", f"Provider returned HTTP {resp.status_code}.",
                        http_status=resp.status_code,
                    )
                else:
                    try:
                        return resp.json()
                    except ValueError:
                        raise ProviderError("INVALID_RESPONSE", "Provider returned invalid JSON.",
                                            http_status=200)
            if attempt < MAX_ATTEMPTS - 1:
                logger.info("provider %s, retry %d (%s)", last_error, attempt + 1, _redact(params))
                await asyncio.sleep(RETRY_BACKOFF_SECONDS[attempt])
                continue
            raise ProviderError(code, f"Provider request failed: {last_error}.",
                                retry_after=retry_after, http_status=last_http)
        raise ProviderError("TEMPORARY", "Provider request failed.")

    @staticmethod
    def _payload_list(data: Any) -> list:
        """Accept common envelope shapes without guessing semantics."""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("episodes", "data", "list", "items", "results", "dramas", "series",
                        "books", "videos", "chapters"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
                if isinstance(value, dict):
                    for nested in ("episodes", "list", "items", "chapters"):
                        if isinstance(value.get(nested), list):
                            return value[nested]
        raise ProviderError("INVALID_RESPONSE", "Provider response has no recognizable list.")


class DramaProvider(abc.ABC):
    """One adapter per content provider. All outputs normalized."""

    name: str = "base"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    @abc.abstractmethod
    async def search_series(self, query: str, *, limit: int = 20):
        ...

    @abc.abstractmethod
    async def get_series(self, series_id: str):
        ...

    @abc.abstractmethod
    async def list_episodes(self, series_id: str, *, cursor: str | None = None):
        ...

    @abc.abstractmethod
    async def get_episode(self, episode_id: str):
        ...


PROVIDERS: dict[str, type[DramaProvider]] = {}


def register_provider(cls: type[DramaProvider]) -> type[DramaProvider]:
    PROVIDERS[cls.name] = cls
    return cls


def get_provider(name: str, transport: httpx.AsyncBaseTransport | None = None,
                 endpoint=None) -> DramaProvider:
    key = (name or "").strip().lower() or "rapidix"
    cls = PROVIDERS.get(key)
    if cls is None:
        supported = ", ".join(sorted(PROVIDERS))
        raise ProviderError(
            "UNSUPPORTED_PROVIDER",
            f"Unknown provider '{name}'. Supported: {supported}.",
        )
    if endpoint is None:
        return cls(transport=transport)
    return cls(transport=transport, endpoint=endpoint)
