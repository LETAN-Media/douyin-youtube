"""Facebook RapidAPI client (Task 4).

Provider: FACEBOOK_RAPIDAPI_HOST (facebook-scraper3).
Chain (verified against live responses):
  GET /page/details?url=<page_url>  -> results.reels_page_id
  GET /page/reels?reels_page_id=<id>&cursor=<cursor>
      -> {"results": [...], "cursor": <next|null>}

Only JSON is consumed. No HTML scraping, no browser, no downloads.
The RapidAPI key never appears in logs or error messages.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import random
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger("backend-facebook.rapidapi")

# Stable error codes (persisted as scan stop_reason / error).
AUTH_ERROR = "RAPIDAPI_AUTH_ERROR"
RATE_LIMITED = "RAPIDAPI_RATE_LIMITED"
QUOTA_EXCEEDED = "RAPIDAPI_QUOTA_EXCEEDED"
UPSTREAM_ERROR = "RAPIDAPI_UPSTREAM_ERROR"
TIMEOUT = "RAPIDAPI_TIMEOUT"
RESPONSE_INVALID = "RAPIDAPI_RESPONSE_INVALID"
END_OF_RESULTS = "END_OF_RESULTS"
SAFETY_LIMIT = "SAFETY_LIMIT"


class RapidApiError(Exception):
    """Typed provider error. Never carries the API key."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass
class RapidApiConfig:
    base_url: str
    host: str
    api_keys: list[str] = field(default_factory=list)
    timeout: float = 20.0
    max_retries: int = 3
    max_pages: int = 200
    max_reels: int = 5000


@dataclass
class ReelsPage:
    items: list[dict]
    next_cursor: str | None
    has_more: bool


def _iso_from_timestamp(value: object) -> str | None:
    try:
        ts = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    try:
        return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def normalize_reel(raw: object) -> dict | None:
    """Normalize one provider item. Returns None when reel_id is missing."""
    if not isinstance(raw, dict):
        return None
    reel_id = raw.get("video_id") or raw.get("reel_id") or raw.get("id")
    if reel_id is None:
        return None
    reel_id = str(reel_id).strip()
    if not reel_id:
        return None
    reel_url = raw.get("url") or f"https://www.facebook.com/reel/{reel_id}/"
    caption = raw.get("description") or raw.get("caption")
    thumbnail = raw.get("thumbnail_uri") or raw.get("thumbnail") or raw.get("image")
    published = None
    for key in ("timestamp", "creation_time", "created_time"):
        if raw.get(key) is not None:
            published = _iso_from_timestamp(raw.get(key))
            if published:
                break
    return {
        "reel_id": reel_id,
        "reel_url": str(reel_url),
        "caption": caption if isinstance(caption, str) else None,
        "thumbnail_url": thumbnail if isinstance(thumbnail, str) else None,
        "source_published_at": published,
    }


def _classify_http_error(status: int, body_snippet: str) -> RapidApiError:
    lowered = (body_snippet or "").lower()
    if status in (401, 403):
        return RapidApiError(AUTH_ERROR, f"Provider auth failed (HTTP {status}).", retryable=False)
    if status == 402 or "quota" in lowered or "exceeded" in lowered:
        return RapidApiError(QUOTA_EXCEEDED, "Provider quota exceeded.", retryable=False)
    if status == 429:
        return RapidApiError(RATE_LIMITED, "Provider rate-limited the request.", retryable=True)
    if 500 <= status <= 599:
        return RapidApiError(UPSTREAM_ERROR, f"Provider upstream error (HTTP {status}).", retryable=True)
    return RapidApiError(UPSTREAM_ERROR, f"Provider request failed (HTTP {status}).", retryable=False)


class FacebookRapidApiClient:
    """Typed wrapper around the reels inventory endpoints. One client per scan."""

    def __init__(self, config: RapidApiConfig) -> None:
        if not config.api_keys:
            raise ValueError("At least one RapidAPI key is required")
        self.config = config

    def _headers(self, key: str) -> dict[str, str]:
        return {"X-RapidAPI-Key": key, "X-RapidAPI-Host": self.config.host}

    def _client(self, key: str, transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=transport,
            base_url=self.config.base_url,
            timeout=self.config.timeout,
            headers=self._headers(key),
        )

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        path: str,
        params: dict,
    ) -> object:
        """GET with retries for transient failures only. Never logs the key."""
        last: RapidApiError | None = None
        for attempt in range(self.config.max_retries):
            try:
                resp = await client.get(path, params=params)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last = RapidApiError(TIMEOUT, f"Provider timeout: {type(exc).__name__}.", retryable=True)
            else:
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError:
                        raise RapidApiError(
                            RESPONSE_INVALID, "Provider returned invalid JSON.", retryable=False
                        )
                snippet = (resp.text or "")[:300]
                err = _classify_http_error(resp.status_code, snippet)
                if not err.retryable:
                    raise err
                last = err
            await asyncio.sleep(min(2**attempt, 8) + random.uniform(0, 0.5))
        assert last is not None
        raise last

    async def _get_json_with_fallback(
        self,
        path: str,
        params: dict,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> object:
        """Try primary key, then fallback key once for auth/rate/quota errors."""
        keys = self.config.api_keys
        try:
            async with self._client(keys[0], transport) as client:
                return await self._get_json(client, path, params)
        except RapidApiError as exc:
            if len(keys) > 1 and exc.code in (AUTH_ERROR, RATE_LIMITED, QUOTA_EXCEEDED):
                logger.warning("primary key hit %s, trying fallback key", exc.code)
                async with self._client(keys[1], transport) as client:
                    return await self._get_json(client, path, params)
            raise

    async def resolve_reels_page_id(
        self,
        page_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> str:
        data = await self._get_json_with_fallback(
            "/page/details", {"url": page_url}, transport=transport
        )
        if not isinstance(data, dict):
            raise RapidApiError(RESPONSE_INVALID, "Page details response is not an object.")
        results = data.get("results")
        if not isinstance(results, dict):
            raise RapidApiError(RESPONSE_INVALID, "Page details has no results object.")
        reels_page_id = results.get("reels_page_id")
        if not reels_page_id or not isinstance(reels_page_id, str):
            raise RapidApiError(RESPONSE_INVALID, "Page details has no reels_page_id.")
        return reels_page_id

    async def list_reels(
        self,
        page_id: str,
        cursor: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        reels_page_id: str | None = None,
    ) -> ReelsPage:
        """One inventory page. page_id is the numeric Page ID (for logs/errors)."""
        rid = reels_page_id or page_id
        params: dict[str, str] = {"reels_page_id": rid}
        if cursor:
            params["cursor"] = cursor
        data = await self._get_json_with_fallback("/page/reels", params, transport=transport)
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise RapidApiError(RESPONSE_INVALID, "Reels response has no results list.")
        items: list[dict] = []
        for raw in data["results"]:
            item = normalize_reel(raw)
            if item is not None:
                items.append(item)
        nxt = data.get("cursor")
        next_cursor = nxt if isinstance(nxt, str) and nxt else None
        return ReelsPage(items=items, next_cursor=next_cursor, has_more=next_cursor is not None)
