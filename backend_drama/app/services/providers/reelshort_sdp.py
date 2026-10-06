"""ReelShort adapter for the Short Drama Pro hub variant.

MCP-verified contract (all GET, distinct from the standalone
reelshort-unofficial-api which uses POST):
- search:   /reelshort/api/v1/search?q=&lang=[&page=]
- detail:   /reelshort/api/v1/book/{id}
- chapters: /reelshort/api/v1/book/{id}/chapters  (the episodes list)

No single-episode endpoint exists here: get_episode resolves from the
chapters list entry. Episode identity prefers the provider id, else
"{book_id}:{number}".
"""

import logging

import httpx

from ...models.drama import (
    EpisodePage,
    NormalizedEpisode,
    NormalizedSeries,
    normalize_episode,
    normalize_series,
)
from .base import DramaProvider, RapidApiProvider, ResolvedEpisodeMedia, register_provider

logger = logging.getLogger("backend-drama-reelshort")


@register_provider
class ReelShortSdpProvider(RapidApiProvider, DramaProvider):
    name = "reelshort_sdp"

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
            "/reelshort/api/v1/search", {"q": query, "lang": "en"}
        )
        out: list[NormalizedSeries] = []
        for item in self._payload_list(data)[: max(1, limit)]:
            try:
                out.append(normalize_series(self.name, item))
            except ValueError as exc:
                logger.warning("reelshort_sdp: skipping unparseable series item: %s", exc)
        return out

    async def get_series(self, series_id: str) -> NormalizedSeries | None:
        data = await self._get(f"/reelshort/api/v1/book/{series_id}", {"lang": "en"})
        payload = data.get("book", data) if isinstance(data, dict) else data
        try:
            return normalize_series(self.name, payload)
        except ValueError as exc:
            logger.warning("reelshort_sdp: unparseable series %s: %s", series_id, exc)
            return None

    async def list_episodes(
        self, series_id: str, *, cursor: str | None = None
    ) -> EpisodePage:
        data = await self._get(
            f"/reelshort/api/v1/book/{series_id}/chapters", {"lang": "en"}
        )
        items = self._payload_list(data)
        episodes: list[NormalizedEpisode] = []
        for i, item in enumerate(items):
            try:
                ep = normalize_episode(self.name, item, fallback_number=i + 1)
            except ValueError as exc:
                logger.warning("reelshort_sdp: skipping unparseable episode: %s", exc)
                continue
            if not ep.external_episode_id:
                ep.external_episode_id = f"{series_id}:{ep.episode_number}"
            episodes.append(ep)
        return EpisodePage(episodes=episodes, next_cursor=None, has_more=False)

    async def get_episode(self, episode_id: str) -> NormalizedEpisode:
        try:
            book_id, ep_num = episode_id.rsplit(":", 1)
            want = int(ep_num)
        except ValueError:
            book_id, want = episode_id, 1
        page = await self.list_episodes(book_id)
        for ep in page.episodes:
            if ep.external_episode_id == episode_id or ep.episode_number == want:
                if not ep.external_episode_id:
                    ep.external_episode_id = episode_id
                return ep
        raise ValueError(f"Episode not found in chapters: {episode_id}")

    async def resolve_episode_media(self, episode_id: str) -> ResolvedEpisodeMedia:
        from .base import extract_media

        ep = await self.get_episode(episode_id)
        return extract_media(self.name, ep.external_episode_id or episode_id, ep.raw)
