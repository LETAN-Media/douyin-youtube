"""RapidIX (RapidAPI marketplace) adapter for short-drama catalog data.

Identity (host/base/key) comes from env. Exact endpoint PATHS are NOT
guessed: they must be copied from the provider's RapidAPI playground code
snippets into RAPIDIX_{SEARCH,EPISODES,EPISODE}_PATH. Until set, provider
methods raise NOT_CONFIGURED and no billable request is ever sent.

Quota discipline: paginated listing only, bounded retries, no bulk crawl.
The key is never logged, never in exception text, never in responses.
"""

import asyncio
import logging
from typing import Any

import httpx

from ..models.drama import (
    EpisodePage,
    NormalizedEpisode,
    NormalizedSeries,
    normalize_episode,
    normalize_series,
)

logger = logging.getLogger("backend-drama-rapidix")

PROVIDER = "rapidix"

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RETRY_BACKOFF_SECONDS = (1.0, 2.0, 4.0)
MAX_ATTEMPTS = len(RETRY_BACKOFF_SECONDS) + 1


class RapidixError(Exception):
    """Typed provider error. Never carries the API key."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _redact(obj: Any) -> Any:
    """Strip key-like material from anything about to be logged."""
    if isinstance(obj, dict):
        return {
            k: ("<redacted>" if "key" in str(k).lower() else _redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [_redact(v) for v in obj]
    if isinstance(obj, str) and len(obj) > 32:
        for marker in ("api-key=", "apikey=", "key="):
            if marker in obj.lower():
                return obj[: obj.lower().index(marker) + len(marker)] + "<redacted>"
    return obj


class RapidixClient:
    def __init__(
        self,
        *,
        base_url: str,
        host: str,
        api_key: str,
        search_path: str | None = None,
        episodes_path: str | None = None,
        episode_path: str | None = None,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not (base_url or "").strip():
            raise RapidixError("NOT_CONFIGURED", "RapidIX base URL is not configured.")
        if not (host or "").strip():
            raise RapidixError("NOT_CONFIGURED", "RapidIX host is not configured.")
        if not (api_key or "").strip():
            raise RapidixError("NOT_CONFIGURED", "RapidIX API key is not configured.")
        self.base_url = base_url.strip().rstrip("/")
        self.host = host.strip()
        self._api_key = api_key.strip()
        self.search_path = (search_path or "").strip() or None
        self.episodes_path = (episodes_path or "").strip() or None
        self.episode_path = (episode_path or "").strip() or None
        self.timeout = timeout_seconds
        self._transport = transport

    @classmethod
    def from_settings(
        cls, transport: httpx.AsyncBaseTransport | None = None
    ) -> "RapidixClient":
        from ..config import settings

        return cls(
            base_url=settings.RAPIDAPI_BASE_URL or "",
            host=settings.RAPIDAPI_HOST or "",
            api_key=settings.RAPIDIX_KEY or "",
            search_path=settings.RAPIDIX_SEARCH_PATH,
            episodes_path=settings.RAPIDIX_EPISODES_PATH,
            episode_path=settings.RAPIDIX_EPISODE_PATH,
            timeout_seconds=settings.RAPIDIX_TIMEOUT_SECONDS,
            transport=transport,
        )

    def _headers(self) -> dict[str, str]:
        return {"x-rapidapi-key": self._api_key, "x-rapidapi-host": self.host}

    async def _request(
        self, method: str, path: str | None, *, params: dict | None = None,
        json_body: dict | None = None,
    ) -> Any:
        if not path:
            raise RapidixError(
                "NOT_CONFIGURED",
                "RapidIX endpoint path is not configured. Copy it from the "
                "provider RapidAPI playground code snippets.",
            )
        last_error = "unknown"
        for attempt in range(MAX_ATTEMPTS):
            try:
                async with httpx.AsyncClient(
                    transport=self._transport,
                    base_url=self.base_url,
                    timeout=self.timeout,
                    headers=self._headers(),
                ) as client:
                    resp = await client.request(
                        method, path, params=params, json=json_body
                    )
            except httpx.TimeoutException:
                last_error = "timeout"
                code = "TIMEOUT"
            except (httpx.ConnectError, httpx.NetworkError):
                last_error = "unreachable"
                code = "TEMPORARY"
            else:
                if resp.status_code == 429:
                    last_error = "rate limited (429)"
                    code = "RATE_LIMITED"
                elif resp.status_code in (500, 502, 503, 504):
                    last_error = f"server error ({resp.status_code})"
                    code = "TEMPORARY"
                elif resp.status_code in (401, 403):
                    raise RapidixError("AUTH_FAILED", "RapidIX rejected the API key.")
                elif resp.status_code != 200:
                    raise RapidixError(
                        "INVALID_RESPONSE",
                        f"RapidIX returned HTTP {resp.status_code}.",
                    )
                else:
                    try:
                        return resp.json()
                    except ValueError:
                        raise RapidixError("INVALID_RESPONSE", "RapidIX returned invalid JSON.")
            if attempt < MAX_ATTEMPTS - 1:
                logger.info(
                    "rapidix %s, retry %d/%d (params=%s)",
                    last_error, attempt + 1, MAX_ATTEMPTS - 1, _redact(params),
                )
                await asyncio.sleep(RETRY_BACKOFF_SECONDS[attempt])
                continue
            raise RapidixError(code, f"RapidIX request failed: {last_error}.")
        raise RapidixError("TEMPORARY", "RapidIX request failed.")

    @staticmethod
    def _payload_list(data: Any) -> list:
        """Accept the common envelope shapes without guessing semantics."""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("episodes", "data", "list", "items", "results", "dramas", "series"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
                if isinstance(value, dict):
                    for nested in ("episodes", "list", "items"):
                        if isinstance(value.get(nested), list):
                            return value[nested]
        raise RapidixError("INVALID_RESPONSE", "RapidIX response has no recognizable list.")

    async def search_series(self, query: str, *, limit: int = 20) -> list[NormalizedSeries]:
        data = await self._request("GET", self.search_path, params={"q": query, "limit": limit})
        out: list[NormalizedSeries] = []
        for item in self._payload_list(data):
            try:
                out.append(normalize_series(PROVIDER, item))
            except ValueError as exc:
                logger.warning("skipping unparseable series item: %s", exc)
        return out

    async def list_episodes(
        self, external_series_id: str, *, cursor: str | None = None, limit: int = 100
    ) -> EpisodePage:
        params: dict[str, Any] = {"series_id": external_series_id, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        data = await self._request("GET", self.episodes_path, params=params)
        items = self._payload_list(data)
        episodes: list[NormalizedEpisode] = []
        for i, item in enumerate(items):
            try:
                episodes.append(normalize_episode(PROVIDER, item, fallback_number=None))
            except ValueError as exc:
                logger.warning("skipping unparseable episode item: %s", exc)
        next_cursor = None
        has_more = False
        if isinstance(data, dict):
            for key in ("next_cursor", "max_cursor", "cursor", "next_page"):
                value = data.get(key)
                if value not in (None, "", 0, "0"):
                    next_cursor = str(value)
                    break
            has_more = bool(data.get("has_more", next_cursor is not None))
        return EpisodePage(episodes=episodes, next_cursor=next_cursor, has_more=has_more)

    async def episode_details(self, external_episode_id: str) -> NormalizedEpisode:
        data = await self._request(
            "GET", self.episode_path, params={"episode_id": external_episode_id}
        )
        payload = data.get("episode", data) if isinstance(data, dict) else data
        try:
            return normalize_episode(PROVIDER, payload)
        except ValueError as exc:
            raise RapidixError("INVALID_RESPONSE", f"Unparseable episode details: {exc}")
