"""DramaBox V4 adapter (Short Drama Pro hub).

MCP-verified contract (all GET):
- search:   /dramaboxv4/api/search?keyword=&lang=&page=
- detail:   /dramaboxv4/api/drama/{bookId}
- episodes: /dramaboxv4/api/drama/{bookId}/episodes
- video:    /dramaboxv4/api/play?bookId=&episode=&lang=

Episode identity is composite "{bookId}:{episode}" (documented: the play
path takes book + episode number, no global episode id).
"""

import logging
from typing import Any

import httpx

from ...models.drama import (
    EpisodePage,
    NormalizedEpisode,
    NormalizedSeries,
    normalize_episode,
    normalize_series,
)
from .base import DramaProvider, RapidApiProvider, ResolvedEpisodeMedia, register_provider

logger = logging.getLogger("backend-drama-dramabox")


@register_provider
class DramaBoxProvider(RapidApiProvider, DramaProvider):
    name = "dramabox"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        from ...config import settings

        super().__init__(
            base_url=settings.DRAMA_API_BASE_URL or "",
            host=settings.DRAMA_API_HOST or "",
            api_key=settings.drama_api_key(),
            timeout_seconds=settings.DRAMA_API_TIMEOUT_SECONDS,
            transport=transport,
        )

    async def search_series(self, query: str, *, limit: int = 20) -> list[NormalizedSeries]:
        data = await self._get(
            "/dramaboxv4/api/search", {"keyword": query, "lang": "en", "page": "1"}
        )
        out: list[NormalizedSeries] = []
        for item in self._payload_list(data)[: max(1, limit)]:
            try:
                out.append(normalize_series(self.name, item))
            except ValueError as exc:
                logger.warning("dramabox: skipping unparseable series item: %s", exc)
        return out

    async def get_series(self, series_id: str) -> NormalizedSeries | None:
        data = await self._get(f"/dramaboxv4/api/drama/{series_id}", {"lang": "en"})
        payload = data.get("drama", data) if isinstance(data, dict) else data
        try:
            return normalize_series(self.name, payload)
        except ValueError as exc:
            logger.warning("dramabox: unparseable series %s: %s", series_id, exc)
            return None

    async def list_episodes(
        self, series_id: str, *, cursor: str | None = None
    ) -> EpisodePage:
        data = await self._get(
            f"/dramaboxv4/api/drama/{series_id}/episodes", {"lang": "en"}
        )
        items = self._payload_list(data)
        episodes: list[NormalizedEpisode] = []
        for i, item in enumerate(items):
            try:
                ep = normalize_episode(self.name, item, fallback_number=i + 1)
            except ValueError as exc:
                logger.warning("dramabox: skipping unparseable episode: %s", exc)
                continue
            if not ep.external_episode_id:
                ep.external_episode_id = f"{series_id}:{ep.episode_number}"
            episodes.append(ep)
        return EpisodePage(episodes=episodes, next_cursor=None, has_more=False)

    async def get_episode(self, episode_id: str) -> NormalizedEpisode:
        try:
            book_id, ep_num = episode_id.rsplit(":", 1)
        except ValueError:
            book_id, ep_num = episode_id, "1"
        data = await self._get(
            "/dramaboxv4/api/play",
            {"bookId": book_id, "episode": ep_num, "lang": "en"},
        )
        payload = data.get("episode", data) if isinstance(data, dict) else data
        ep = normalize_episode(self.name, payload, fallback_number=int(ep_num or 1))
        if not ep.external_episode_id:
            ep.external_episode_id = f"{book_id}:{ep.episode_number}"
        return ep

    async def resolve_episode_media(self, episode_id: str) -> ResolvedEpisodeMedia:
        from .base import extract_media

        ep = await self.get_episode(episode_id)
        return extract_media(self.name, ep.external_episode_id or episode_id, ep.raw)
