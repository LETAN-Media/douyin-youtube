"""Provider registry + per-provider contracts (mocked transports).

Paths/params mirror the MCP-verified Short Drama Pro contracts. Response
bodies are representative shapes (real shapes pending live verification);
tests assert wiring (paths, params, normalization, registry) — never live.
"""

import asyncio

import httpx
import pytest

from app.services.providers import PROVIDERS, get_provider
from app.services.providers.base import ProviderError, extract_media, mask_url


def run(coro):
    return asyncio.run(coro)


def test_registry_has_all_providers():
    for name in (
        "rapidix", "starshort", "dramabox", "flickshort",
        "netshort", "shortmax", "reelshort_sdp",
    ):
        assert name in PROVIDERS, name


def test_unknown_provider_errors():
    with pytest.raises(ProviderError) as exc:
        get_provider("nope_sdp")
    assert exc.value.code == "UNSUPPORTED_PROVIDER"
    assert "nope_sdp" in str(exc.value)


def test_mask_url_strips_signature():
    assert mask_url("https://cdn.example.com/v/a.m3u8?token=SECRET&x=1") == \
        "cdn.example.com/v/a.m3u8"
    assert "SECRET" not in mask_url("https://h.com/p?token=SECRET")


def test_extract_media_presence_only():
    m = extract_media("starshort", "d1:1", {
        "play_url": "https://cdn.example.com/v/1.m3u8?sig=ABC",
        "subtitles": [{"lang": "en"}],
        "duration": "95",
    })
    assert m.video_type == "hls"
    assert m.has_subtitle is True
    assert m.duration == 95.0
    assert m.video_url == "https://cdn.example.com/v/1.m3u8?sig=ABC"
    # Reporting layer must mask signatures, never the stored value itself.
    assert mask_url(m.video_url or "") == "cdn.example.com/v/1.m3u8"


def _starshort_search_payload():
    return {"data": [
        {"id": "d123", "title": "Love Story", "cover": "https://cdn.example.com/c.jpg",
         "episodeCount": 80},
    ]}


def test_starshort_search_posts_expected_shape():
    import json as _json

    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        seen.update(_json.loads(req.content.decode() or "{}"))
        return httpx.Response(200, json=_starshort_search_payload())

    async def _go():
        p = get_provider("starshort", transport=httpx.MockTransport(handler))
        return await p.search_series("love")

    out = run(_go())
    assert seen["path"] == "/starshort/api/v1/dramas/search"
    assert len(out) == 1 and out[0].external_series_id == "d123"


def test_starshort_episodes_and_episode():
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path.endswith("/episodes"):
            return httpx.Response(200, json={"episodes": [
                {"id": "e1", "episode_number": 1, "title": "Ep 1"},
                {"id": "e2", "episode_number": 2, "title": "Ep 2"},
            ]})
        return httpx.Response(200, json={"id": "e1", "episode_number": 1,
                                         "play_url": "https://cdn.example.com/e1.m3u8"})

    async def _go():
        p = get_provider("starshort", transport=httpx.MockTransport(handler))
        page = await p.list_episodes("d123")
        assert [e.episode_number for e in page.episodes] == [1, 2]
        ep = await p.get_episode("d123:1")
        assert ep.external_episode_id == "e1"
        media = await p.resolve_episode_media("d123:1")
        assert media.video_type == "hls"
        assert media.video_url == "https://cdn.example.com/e1.m3u8"

    run(_go())


def test_dramabox_search_uses_keyword():
    import json as _json

    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        seen.update(dict(req.url.params))
        assert req.method == "GET"
        if req.url.path.endswith("/episodes"):
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, json={"data": [{"bookId": "b9", "title": "B"}]})

    async def _go():
        p = get_provider("dramabox", transport=httpx.MockTransport(handler))
        out = await p.search_series("love")
        assert out[0].external_series_id == "b9"
        page = await p.list_episodes("b9")
        assert page.episodes == []
        ep = await p.get_episode("b9:3")
        assert ep.external_episode_id == "b9:3" and ep.episode_number == 3

    def empty_handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    async def _go2():
        p = get_provider("dramabox", transport=httpx.MockTransport(empty_handler))
        page = await p.list_episodes("b9")
        assert page.episodes == []

    run(_go())
    assert seen.get("keyword") == "love"
    run(_go2())


def test_flickshort_episode_composite_id():
    def handler(req: httpx.Request) -> httpx.Response:
        assert "/episode/4" in req.url.path
        return httpx.Response(200, json={"title": "Ep 4"})

    async def _go():
        p = get_provider("flickshort", transport=httpx.MockTransport(handler))
        ep = await p.get_episode("d7:4")
        assert (ep.external_episode_id, ep.episode_number) == ("d7:4", 4)

    run(_go())


def test_netshort_search_unsupported_but_episode_works():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "n1", "episode_number": 2})

    async def _go():
        p = get_provider("netshort", transport=httpx.MockTransport(handler))
        with pytest.raises(ProviderError) as exc:
            await p.search_series("love")
        assert exc.value.code == "UNSUPPORTED"
        ep = await p.get_episode("n1:2")
        assert ep.external_episode_id == "n1"

    run(_go())


def test_shortmax_search_and_list_unsupported():
    async def _go():
        p = get_provider("shortmax")
        with pytest.raises(ProviderError) as exc:
            await p.search_series("love")
        assert exc.value.code == "UNSUPPORTED"
        with pytest.raises(ProviderError):
            await p.list_episodes("c1")

    run(_go())


def test_reelshort_sdp_chapters_as_episodes():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/reelshort/api/v1/book/b5/chapters"
        return httpx.Response(200, json={"chapters": [
            {"chapter_id": "c1", "chapter_number": 1},
            {"chapter_id": "c2", "chapter_number": 2},
        ]})

    async def _go():
        p = get_provider("reelshort_sdp", transport=httpx.MockTransport(handler))
        page = await p.list_episodes("b5")
        assert [e.episode_number for e in page.episodes] == [1, 2]
        ep = await p.get_episode("b5:2")
        assert ep.external_episode_id == "c2"

    run(_go())


def test_rapidix_wrapper_delegates():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"episodes": []})

    async def _go():
        p = get_provider("rapidix", transport=httpx.MockTransport(handler))
        page = await p.list_episodes("b1")
        assert page.episodes == []
        assert await p.get_series("b1") is None

    run(_go())


def test_provider_auth_error_typed():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "not subscribed"})

    async def _go():
        p = get_provider("starshort", transport=httpx.MockTransport(handler))
        with pytest.raises(ProviderError) as exc:
            await p.search_series("love")
        assert exc.value.code == "AUTH_FAILED"

    run(_go())


def test_scanner_uses_registry_provider(db):
    from app.db.repositories import drama as repo
    from app.services.scanner import scan_source

    p = repo.create_pipeline(name="Reg Show")
    src = repo.create_source(pipeline_id=p["id"], provider="starshort",
                             external_series_id="d123")

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"episodes": [
            {"id": "e1", "episode_number": 1, "title": "Ep 1"},
        ]})

    import app.services.scanner as scanner_mod
    from app.services.providers import pool as pool_mod
    from app.models.drama import EpisodePage, NormalizedEpisode

    seen: dict = {}

    async def fake_execute(provider_name, operation, transport=None, **kwargs):
        seen["provider"] = provider_name
        seen["operation"] = operation
        if operation == "get_series":
            return None, "primary"
        return EpisodePage(episodes=[
            NormalizedEpisode(provider="starshort", external_episode_id="e9",
                              episode_number=9, title="Ep 9"),
        ], next_cursor=None, has_more=False), "primary"

    orig_execute = pool_mod.execute
    pool_mod.execute = fake_execute
    try:
        out = asyncio_run(scan_source(src["id"]))
    finally:
        pool_mod.execute = orig_execute
    assert out["inserted"] == 1 and out["episodes_found"] == 1
    assert seen == {"provider": "starshort", "operation": "list_episodes"}
    items, total = repo.list_episodes(out["series_id"])
    assert total == 1 and items[0]["episode_number"] == 9


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)
