"""StarShort adapter (Short Drama Pro hub). First fully-implemented provider.

MCP-verified contract (all GET):
- search:   /starshort/api/v1/dramas/search?q=&lang=
- detail:   /starshort/api/v1/dramas/{dramaId}
- episodes: /starshort/api/v1/dramas/{dramaId}/episodes
- episode:  /starshort/api/v1/dramas/{dramaId}/episodes/{epNum}

Episode identity is composite "{dramaId}:{epNum}" (documented here because
the provider has no separate global episode id in the episode path).
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

logger = logging.getLogger("backend-drama-starshort")


@register_provider
class StarShortProvider(RapidApiProvider, DramaProvider):
    name = "starshort"

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
            "/starshort/api/v1/dramas/search", {"q": query, "lang": "en"}
        )
        out: list[NormalizedSeries] = []
        for item in self._payload_list(data)[: max(1, limit)]:
            try:
                out.append(normalize_series(self.name, item))
            except ValueError as exc:
                logger.warning("starshort: skipping unparseable series item: %s", exc)
        return out

    async def get_series(self, series_id: str) -> NormalizedSeries | None:
        data = await self._get(f"/starshort/api/v1/dramas/{series_id}", {"lang": "en"})
        payload = data.get("drama", data) if isinstance(data, dict) else data
        try:
            return normalize_series(self.name, payload)
        except ValueError as exc:
            logger.warning("starshort: unparseable series %s: %s", series_id, exc)
            return None

    async def list_episodes(
        self, series_id: str, *, cursor: str | None = None
    ) -> EpisodePage:
        data = await self._get(
            f"/starshort/api/v1/dramas/{series_id}/episodes", {"lang": "en"}
        )
        items = self._payload_list(data)
        episodes: list[NormalizedEpisode] = []
        for i, item in enumerate(items):
            try:
                ep = normalize_episode(self.name, item, fallback_number=i + 1)
            except ValueError as exc:
                logger.warning("starshort: skipping unparseable episode: %s", exc)
                continue
            if not ep.external_episode_id:
                ep.external_episode_id = f"{series_id}:{ep.episode_number}"
            episodes.append(ep)
        return EpisodePage(episodes=episodes, next_cursor=None, has_more=False)

    async def get_episode(self, episode_id: str) -> NormalizedEpisode:
        try:
            drama_id, ep_num = episode_id.rsplit(":", 1)
        except ValueError:
            drama_id, ep_num = episode_id, "1"
        data = await self._get(
            f"/starshort/api/v1/dramas/{drama_id}/episodes/{ep_num}", {"lang": "en"}
        )
        payload = data.get("episode", data) if isinstance(data, dict) else data
        ep = normalize_episode(self.name, payload, fallback_number=int(ep_num or 1))
        if not ep.external_episode_id:
            ep.external_episode_id = f"{drama_id}:{ep.episode_number}"
        return ep

    async def resolve_episode_media(self, episode_id: str) -> ResolvedEpisodeMedia:
        from .base import extract_media

        ep = await self.get_episode(episode_id)
        return extract_media(self.name, ep.external_episode_id or episode_id, ep.raw)
