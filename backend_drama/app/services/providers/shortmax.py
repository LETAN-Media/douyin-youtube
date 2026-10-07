"""ShortMax adapter (Short Drama Pro hub).

MCP-verified contract (all GET): genre feeds
(/shortmax/api/v1/feed/{ranked,romance,new,war,foryou}), home, languages,
and a resolver /shortmax/api/v1/play/{code}?ep=&lang=.

No keyword search and no episodes list exist: search_series and
list_episodes raise UNSUPPORTED (feed discovery belongs to a later phase).
Single episodes resolve via play/{code}. Episode identity is "{code}:{ep}".
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

logger = logging.getLogger("backend-drama-shortmax")


@register_provider
class ShortMaxProvider(RapidApiProvider, DramaProvider):
    name = "shortmax"

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
            "ShortMax exposes no keyword search endpoint; discover series "
            "via genre feeds instead.",
        )

    async def discover_series(self, *, limit: int = 20) -> list[NormalizedSeries]:
        try:
            data = await self._get("/shortmax/api/v1/feed/ranked", {"lang": "en"})
        except ProviderError as exc:
            if exc.code in ("NOT_FOUND", "TEMPORARY"):
                data = await self._get("/shortmax/api/v1/home", {"lang": "en"})
            else:
                raise
        out: list[NormalizedSeries] = []
        for item in self._payload_list(data)[: max(1, limit)]:
            try:
                out.append(normalize_series(self.name, item))
            except ValueError as exc:
                logger.warning("shortmax: skipping unparseable series in discover: %s", exc)
                continue
        return out

    async def get_series(self, series_id: str) -> NormalizedSeries | None:
        raise ProviderError(
            "UNSUPPORTED",
            "ShortMax exposes no series detail endpoint; resolve single "
            "episodes via play/{code} instead.",
        )

    async def list_episodes(
        self, series_id: str, *, cursor: str | None = None
    ) -> EpisodePage:
        raise ProviderError(
            "UNSUPPORTED",
            "ShortMax exposes no episodes-list endpoint.",
        )

    async def get_episode(self, episode_id: str) -> NormalizedEpisode:
        try:
            code, ep_num = episode_id.rsplit(":", 1)
        except ValueError:
            code, ep_num = episode_id, "1"
        data = await self._get(
            f"/shortmax/api/v1/play/{code}", {"ep": ep_num, "lang": "en"}
        )
        payload = data.get("episode", data) if isinstance(data, dict) else data
        ep = normalize_episode(self.name, payload, fallback_number=int(ep_num or 1))
        if not ep.external_episode_id:
            ep.external_episode_id = f"{code}:{ep.episode_number}"
        return ep

    async def resolve_episode_media(self, episode_id: str) -> ResolvedEpisodeMedia:
        from .base import extract_media

        ep = await self.get_episode(episode_id)
        return extract_media(self.name, ep.external_episode_id or episode_id, ep.raw)
