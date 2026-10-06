"""NetShort adapter (Short Drama Pro hub).

MCP-verified contract (all GET):
- detail:  /netshort/api/v1/detail/{id}
- episode: /netshort/api/v1/episode/{id}/{episodeNo}
- feeds:   /netshort/api/v1/feed|explore|category|vip|dubbing/{page}, tabs...

Deliberately NO search endpoint in this provider: search_series raises
UNSUPPORTED (discover via feeds in a later phase). Episodes are enumerated
from the detail payload when it embeds a list, else UNSUPPORTED.
Episode identity is composite "{id}:{episodeNo}".
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

logger = logging.getLogger("backend-drama-netshort")

_EMBEDDED_LIST_KEYS = ("episodes", "episode_list", "chapters", "videos", "list", "items")


@register_provider
class NetShortProvider(RapidApiProvider, DramaProvider):
    name = "netshort"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None,
                 endpoint=None) -> None:
        from ...config import settings

        if endpoint is not None:
            base_url, host, api_key = endpoint.base_url, endpoint.host, endpoint.api_key
        else:
            base_url, host, api_key = (
                settings.DRAMA_API_BASE_URL or "",
                settings.DRAMA_API_HOST or "",
                settings.drama_api_key(),
            )
        super().__init__(
            base_url=base_url,
            host=host,
            api_key=api_key,
            timeout_seconds=settings.DRAMA_API_TIMEOUT_SECONDS,
            transport=transport,
        )

    async def search_series(self, query: str, *, limit: int = 20) -> list[NormalizedSeries]:
        raise ProviderError(
            "UNSUPPORTED",
            "NetShort exposes no keyword search endpoint; discover series "
            "via feed/explore pages instead.",
        )

    async def get_series(self, series_id: str) -> NormalizedSeries | None:
        data = await self._get(f"/netshort/api/v1/detail/{series_id}", {"lang": "en"})
        payload = data.get("drama", data) if isinstance(data, dict) else data
        try:
            return normalize_series(self.name, payload)
        except ValueError as exc:
            logger.warning("netshort: unparseable series %s: %s", series_id, exc)
            return None

    async def list_episodes(
        self, series_id: str, *, cursor: str | None = None
    ) -> EpisodePage:
        data = await self._get(f"/netshort/api/v1/detail/{series_id}", {"lang": "en"})
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
                "NetShort detail payload embeds no episode list for this series.",
            )
        episodes: list[NormalizedEpisode] = []
        for i, item in enumerate(embedded):
            try:
                ep = normalize_episode(self.name, item, fallback_number=i + 1)
            except ValueError as exc:
                logger.warning("netshort: skipping unparseable episode: %s", exc)
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
            f"/netshort/api/v1/episode/{drama_id}/{ep_num}", {"lang": "en"}
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
