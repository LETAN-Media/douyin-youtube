"""Legacy rapidix adapter (reelshort-unofficial-api, POST contract).

Kept for backward compatibility with existing 'rapidix' sources/rows.
New sources should use the Short Drama Pro providers instead.
"""

import logging

import httpx

from ...models.drama import EpisodePage, NormalizedEpisode, NormalizedSeries
from ..rapidix import RapidixClient
from .base import DramaProvider, register_provider

logger = logging.getLogger("backend-drama-rapidix-provider")


@register_provider
class RapidixProvider(DramaProvider):
    name = "rapidix"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None,
                 endpoint=None) -> None:
        super().__init__(transport=transport)
        self._endpoint = endpoint
        self._client: RapidixClient | None = None

    def _get_client(self) -> RapidixClient:
        if self._client is None:
            if self._endpoint is not None and (
                "rapidix" in self._endpoint.providers
                or "reelshort-unofficial" in self._endpoint.host
                or self._endpoint.name.startswith("rapidix")
            ):
                from ...config import settings

                self._client = RapidixClient(
                    base_url=self._endpoint.base_url,
                    host=self._endpoint.host,
                    api_key=self._endpoint.api_key,
                    search_path=settings.RAPIDIX_SEARCH_PATH,
                    episodes_path=settings.RAPIDIX_EPISODES_PATH,
                    episode_path=settings.RAPIDIX_EPISODE_PATH,
                    timeout_seconds=settings.RAPIDIX_TIMEOUT_SECONDS,
                    transport=self._transport,
                )
            else:
                self._client = RapidixClient.from_settings(transport=self._transport)
        return self._client

    async def search_series(self, query: str, *, limit: int = 20) -> list[NormalizedSeries]:
        return await self._get_client().search_series(query, limit=limit)

    async def get_series(self, series_id: str) -> NormalizedSeries | None:
        # Legacy provider has no detail endpoint; the scanner upserts a
        # shell series row and fills metadata from episode payloads.
        _ = series_id
        return None

    async def list_episodes(
        self, series_id: str, *, cursor: str | None = None
    ) -> EpisodePage:
        return await self._get_client().list_episodes(series_id, cursor=cursor)

    async def get_episode(self, episode_id: str) -> NormalizedEpisode:
        return await self._get_client().episode_details(episode_id)
