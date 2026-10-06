"""FlickShort adapter (Short Drama Pro hub).

MCP-verified contract (all GET):
- search:  /flickshort/api/v1/search?q=&lang=[&limit=]
- detail:  /flickshort/api/v1/drama/{id}
- episode: /flickshort/api/v1/drama/{id}/episode/{ep}

No dedicated episodes-list endpoint exists: list_episodes reuses the
detail payload when it embeds an episode list, otherwise raises
UNSUPPORTED (the scanner then cannot enumerate — use search + detail).
Episode identity is composite "{id}:{ep}".
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
from .base import (
    DramaProvider,
    ProviderError,
    RapidApiProvider,
    ResolvedEpisodeMedia,
    register_provider,
)

logger = logging.getLogger("backend-drama-flickshort")

_EMBEDDED_LIST_KEYS = ("episodes", "episode_list", "chapters", "videos", "list", "items")


@register_provider
class FlickShortProvider(RapidApiProvider, DramaProvider):
    name = "flickshort"

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
            "/flickshort/api/v1/search", {"q": query, "lang": "en"}
        )
        out: list[NormalizedSeries] = []
        for item in self._payload_list(data)[: max(1, limit)]:
            try:
                out.append(normalize_series(self.name, item))
            except ValueError as exc:
                logger.warning("flickshort: skipping unparseable series item: %s", exc)
        return out

    async def get_series(self, series_id: str) -> NormalizedSeries | None:
        data = await self._get(f"/flickshort/api/v1/drama/{series_id}", {"lang": "en"})
        payload = data.get("drama", data) if isinstance(data, dict) else data
        try:
            return normalize_series(self.name, payload)
        except ValueError as exc:
            logger.warning("flickshort: unparseable series %s: %s", series_id, exc)
            return None

    async def list_episodes(
        self, series_id: str, *, cursor: str | None = None
    ) -> EpisodePage:
        data = await self._get(f"/flickshort/api/v1/drama/{series_id}", {"lang": "en"})
        payload = data.get("drama", data) if isinstance(data, dict) else data
        embedded: list | None = None
        if isinstance(payload, dict):
            for key in _EMBEDDED_LIST_KEYS:
                if isinstance(payload.get(key), list):
                    embedded = payload[key]
                    break
        if not embedded:
            raise ProviderError(
                "UNSUPPORTED",
                "FlickShort exposes no episodes-list endpoint and this detail "
                "payload embeds no episode list.",
            )
        episodes: list[NormalizedEpisode] = []
        for i, item in enumerate(embedded):
            try:
                ep = normalize_episode(self.name, item, fallback_number=i + 1)
            except ValueError as exc:
                logger.warning("flickshort: skipping unparseable episode: %s", exc)
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
            f"/flickshort/api/v1/drama/{drama_id}/episode/{ep_num}", {"lang": "en"}
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
