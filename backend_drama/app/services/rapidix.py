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
    _as_int,
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
            api_key=settings.rapidix_key(),
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
                elif resp.status_code in (404, 422):
                    raise RapidixError(
                        "NOT_FOUND",
                        f"RapidIX resource not found ({resp.status_code}).",
                    )
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
            for key in (
                "episodes", "data", "list", "items", "results", "dramas",
                "series", "chapterList", "chapters", "online_base",
            ):
                value = data.get(key)
                if isinstance(value, list):
                    return value
                if isinstance(value, dict):
                    for nested in (
                        "episodes", "list", "items", "chapterList", "chapters",
                        "data", "online_base",
                    ):
                        if isinstance(value.get(nested), list):
                            return value[nested]
        raise RapidixError("INVALID_RESPONSE", "RapidIX response has no recognizable list.")

    async def _fetch_reelshort_web(
        self, external_series_id: str
    ) -> tuple[NormalizedSeries | None, list[NormalizedEpisode]]:
        """Fallback to ReelShort public metadata when upstream API fails or is rate limited."""
        import json
        import re

        url = f"https://www.reelshort.com/movie/{external_series_id}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=self.timeout,
                headers=headers,
            ) as client:
                resp = await client.get(url)
            if resp.status_code != 200:
                return None, []
            m = re.search(r"<script id=\"__NEXT_DATA__\" type=\"application/json\">(.*?)</script>", resp.text)
            if not m:
                return None, []
            raw_json = json.loads(m.group(1))
            page_data = raw_json.get("props", {}).get("pageProps", {}).get("data", {})
            if not page_data or not isinstance(page_data, dict):
                return None, []

            series = NormalizedSeries(
                provider=PROVIDER,
                external_series_id=str(page_data.get("book_id") or external_series_id),
                title=page_data.get("book_title"),
                description=page_data.get("special_desc"),
                thumbnail_url=page_data.get("book_pic"),
                total_episodes=_as_int(page_data.get("total_chapter") or page_data.get("total")),
                raw=page_data,
            )

            chapters = page_data.get("online_base", [])
            episodes: list[NormalizedEpisode] = []
            for item in chapters:
                if not isinstance(item, dict):
                    continue
                num = _as_int(item.get("serial_number") or item.get("chapter_weight") or item.get("chapter_index"))
                cid = item.get("chapter_id")
                thumb = item.get("video_pic")
                episodes.append(
                    NormalizedEpisode(
                        provider=PROVIDER,
                        external_episode_id=str(cid) if cid else f"{external_series_id}:{num}",
                        episode_number=num if num is not None else len(episodes) + 1,
                        title=f"Tập {num}" if num else None,
                        source_url=f"https://www.reelshort.com/movie/{external_series_id}",
                        thumbnail_url=thumb,
                        duration=None,
                        raw=item,
                    )
                )
            episodes.sort(key=lambda e: e.episode_number)
            if series.total_episodes is None or series.total_episodes < len(episodes):
                series.total_episodes = len(episodes)
            return series, episodes
        except Exception as exc:
            logger.warning("ReelShort web fallback failed for %s: %s", external_series_id, exc)
            return None, []

    async def get_series(self, external_series_id: str) -> NormalizedSeries | None:
        if self._transport is not None:
            return None
        series, _ = await self._fetch_reelshort_web(external_series_id)
        return series

    async def search_series(self, query: str, *, limit: int = 20) -> list[NormalizedSeries]:
        data = await self._request(
            "POST", self.search_path, json_body={"keyword": query}
        )
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
        items = []
        next_cursor = None
        has_more = False

        try:
            body: dict[str, Any] = {"id": external_series_id}
            # Send the observed cursor back on subsequent pages. The live
            # API returns complete lists (no cursor observed yet); unknown
            # fields are ignored by typical providers, and this keeps the
            # loop honest if pagination ever appears.
            if cursor:
                body["cursor"] = cursor
            data = await self._request("POST", self.episodes_path, json_body=body)
            items = self._payload_list(data)
            if isinstance(data, dict):
                for key in ("next_cursor", "max_cursor", "cursor", "next_page"):
                    value = data.get(key)
                    if value not in (None, "", 0, "0"):
                        next_cursor = str(value)
                        break
                has_more = bool(data.get("has_more", next_cursor is not None))
        except RapidixError as exc:
            if self._transport is not None:
                raise
            logger.info("RapidAPI list_episodes error (%s: %s), falling back to ReelShort web", exc.code, exc)
            _, web_eps = await self._fetch_reelshort_web(external_series_id)
            if web_eps:
                return EpisodePage(episodes=web_eps, next_cursor=None, has_more=False)
            if exc.code == "RATE_LIMITED":
                raise RapidixError("RAPIDIX_RATE_LIMITED", "RapidIX upstream rate limit reached.")
            if exc.code in ("NOT_FOUND", "INVALID_RESPONSE"):
                raise RapidixError("RAPIDIX_SERIES_NOT_FOUND", f"RapidIX series '{external_series_id}' not found.")
            raise RapidixError("RAPIDIX_UPSTREAM_ERROR", f"RapidIX request failed: {exc}")

        episodes: list[NormalizedEpisode] = []
        for i, item in enumerate(items):
            try:
                episodes.append(normalize_episode(PROVIDER, item, fallback_number=i + 1))
            except ValueError as exc:
                logger.warning("skipping unparseable episode item: %s", exc)

        if not episodes and self._transport is None:
            _, web_eps = await self._fetch_reelshort_web(external_series_id)
            if web_eps:
                return EpisodePage(episodes=web_eps, next_cursor=None, has_more=False)

        episodes.sort(key=lambda e: int(e.episode_number))
        return EpisodePage(episodes=episodes, next_cursor=next_cursor, has_more=has_more)

    async def episode_details(self, external_episode_id: str) -> NormalizedEpisode:
        data = await self._request(
            "POST", self.episode_path, json_body={"episode_id": external_episode_id}
        )
        payload = data.get("episode", data) if isinstance(data, dict) else data
        try:
            return normalize_episode(PROVIDER, payload)
        except ValueError as exc:
            raise RapidixError("INVALID_RESPONSE", f"Unparseable episode details: {exc}")
