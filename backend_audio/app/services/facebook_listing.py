"""Facebook listing provider for Audio (facebook-scraper3 via RapidAPI).

Verified chain (mirrors the proven backend_facebook adapter):
  GET /page/details?url=<page_url>  -> results.reels_page_id
  GET /page/reels?reels_page_id=<id>&cursor=<cursor>
      -> {"results": [...], "cursor": <next|null>}

Single API key from AUDIO_RAPIDAPI_KEY. No key rotation: quota errors stop
the scan instead of burning fallback keys. The key never appears in logs.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import random
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger("backend-audio.listing")

AUTH_ERROR = "LISTING_AUTH_ERROR"
QUOTA_EXCEEDED = "LISTING_QUOTA_EXCEEDED"
RATE_LIMITED = "LISTING_RATE_LIMITED"
TIMEOUT = "LISTING_TIMEOUT"
UPSTREAM_ERROR = "LISTING_UPSTREAM_ERROR"
RESPONSE_INVALID = "LISTING_RESPONSE_INVALID"
NOT_CONFIGURED = "LISTING_NOT_CONFIGURED"
END_OF_RESULTS = "END_OF_RESULTS"
SAFETY_LIMIT = "SAFETY_LIMIT"
KNOWN_ITEMS_REACHED = "KNOWN_ITEMS_REACHED"


class ListingError(Exception):
    """Typed provider error. Never carries the API key."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass
class ListingConfig:
    base_url: str
    host: str
    api_key: str
    timeout: float = 20.0
    max_retries: int = 3


@dataclass
class VideoPage:
    items: list[dict]
    next_cursor: str | None
    has_more: bool


def _iso_from_timestamp(value: object) -> str | None:
    try:
        ts = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    try:
        return datetime.datetime.fromtimestamp(
            ts, tz=datetime.timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def normalize_video(raw: object) -> dict | None:
    """Normalize one provider item. Returns None when the video id is missing."""
    if not isinstance(raw, dict):
        return None
    video_id = raw.get("video_id") or raw.get("reel_id") or raw.get("id")
    if video_id is None:
        return None
    video_id = str(video_id).strip()
    if not video_id:
        return None
    url = raw.get("url") or f"https://www.facebook.com/reel/{video_id}/"
    caption = raw.get("description") or raw.get("caption")
    thumbnail = (raw.get("thumbnail_uri") or raw.get("thumbnail")
                 or raw.get("image"))
    duration = raw.get("duration") or raw.get("length")
    try:
        duration = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration = None
    published = None
    for key in ("timestamp", "creation_time", "created_time"):
        if raw.get(key) is not None:
            published = _iso_from_timestamp(raw.get(key))
            if published:
                break
    return {
        "video_id": video_id,
        "url": str(url),
        "caption": caption if isinstance(caption, str) else None,
        "thumbnail_url": thumbnail if isinstance(thumbnail, str) else None,
        "duration_seconds": duration,
        "source_published_at": published,
    }


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    try:
        value = float((resp.headers.get("retry-after") or "").strip())
        if 0 < value <= 600:
            return value
    except (TypeError, ValueError):
        pass
    return None


def _classify(status: int, body_snippet: str) -> ListingError:
    lowered = (body_snippet or "").lower()
    if status in (401, 403):
        return ListingError(AUTH_ERROR, f"Listing auth failed (HTTP {status}).",
                            retryable=False)
    if status == 402 or "quota" in lowered or "exceeded" in lowered:
        return ListingError(QUOTA_EXCEEDED, "Listing quota exceeded.",
                            retryable=False)
    if status == 429:
        return ListingError(RATE_LIMITED, "Listing rate-limited (429).",
                            retryable=True)
    if 500 <= status <= 599:
        return ListingError(UPSTREAM_ERROR, f"Listing upstream error ({status}).",
                            retryable=True)
    return ListingError(UPSTREAM_ERROR, f"Listing request failed ({status}).",
                        retryable=False)


class FacebookListingClient:
    """Typed wrapper around the reels inventory endpoints. One per scan."""

    def __init__(self, config: ListingConfig,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not config.api_key:
            raise ListingError(NOT_CONFIGURED, "AUDIO_RAPIDAPI_KEY is not set.")
        self.config = config
        self._transport = transport

    @classmethod
    def from_settings(
        cls, transport: httpx.AsyncBaseTransport | None = None
    ) -> "FacebookListingClient":
        from app.config import settings

        return cls(ListingConfig(
            base_url=(settings.AUDIO_RAPIDAPI_BASE_URL or "").strip().rstrip("/"),
            host=(settings.AUDIO_RAPIDAPI_HOST or "").strip(),
            api_key=(settings.AUDIO_RAPIDAPI_KEY or "").strip(),
            timeout=float(settings.AUDIO_RAPIDAPI_TIMEOUT or 20.0)),
            transport=transport)

    async def _get_json(self, path: str, params: dict) -> object:
        last: ListingError | None = None
        async with httpx.AsyncClient(
            transport=self._transport, base_url=self.config.base_url,
            timeout=self.config.timeout,
            headers={"X-RapidAPI-Key": self.config.api_key,
                     "X-RapidAPI-Host": self.config.host},
        ) as client:
            for attempt in range(self.config.max_retries):
                try:
                    resp = await client.get(path, params=params)
                except (httpx.TimeoutException, httpx.ConnectError) as exc:
                    last = ListingError(
                        TIMEOUT, f"Listing timeout: {type(exc).__name__}.",
                        retryable=True)
                else:
                    if resp.status_code == 200:
                        try:
                            return resp.json()
                        except ValueError:
                            raise ListingError(RESPONSE_INVALID,
                                               "Listing returned invalid JSON.")
                    err = _classify(resp.status_code, (resp.text or "")[:300])
                    if not err.retryable:
                        raise err
                    wait = _retry_after_seconds(resp)
                    if wait is not None:
                        await asyncio.sleep(wait)
                        continue
                    last = err
                await asyncio.sleep(min(2 ** attempt, 8) + random.uniform(0, 0.5))
        assert last is not None
        raise last

    async def resolve_reels_page_id(self, page_url: str) -> str:
        data = await self._get_json("/page/details", {"url": page_url})
        if not isinstance(data, dict):
            raise ListingError(RESPONSE_INVALID, "Page details is not an object.")
        results = data.get("results")
        if not isinstance(results, dict):
            raise ListingError(RESPONSE_INVALID, "Page details has no results.")
        reels_page_id = results.get("reels_page_id")
        if not reels_page_id or not isinstance(reels_page_id, str):
            raise ListingError(RESPONSE_INVALID, "Page details has no reels_page_id.")
        return reels_page_id

    async def list_videos(self, page_id: str, cursor: str | None = None,
                          *, reels_page_id: str | None = None) -> VideoPage:
        rid = reels_page_id or page_id
        params: dict[str, str] = {"reels_page_id": rid}
        if cursor:
            params["cursor"] = cursor
        data = await self._get_json("/page/reels", params)
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise ListingError(RESPONSE_INVALID, "Reels response has no results.")
        items = []
        for raw in data["results"]:
            item = normalize_video(raw)
            if item is not None:
                items.append(item)
        nxt = data.get("cursor")
        next_cursor = nxt if isinstance(nxt, str) and nxt else None
        return VideoPage(items=items, next_cursor=next_cursor,
                         has_more=next_cursor is not None)
