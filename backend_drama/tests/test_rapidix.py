"""RapidixClient: normalization variants, typed errors, retry, redaction.

No production key, no live calls — httpx.MockTransport throughout.
"""

import httpx
import pytest

from app.services.rapidix import (
    EpisodePage,
    RapidixClient,
    RapidixError,
    _redact,
    normalize_episode,
    normalize_series,
)


def make_client(transport=None, **overrides):
    kwargs = {
        "base_url": "https://test-host.p.rapidapi.com",
        "host": "test-host.p.rapidapi.com",
        "api_key": "test_rapidix_key",
        "search_path": "/search",
        "episodes_path": "/episodes",
        "episode_path": "/episode",
        "transport": transport,
    }
    kwargs.update(overrides)
    return RapidixClient(**kwargs)


def test_missing_paths_refuse_without_http():
    async def _run():
        client = make_client(search_path=None)
        with pytest.raises(RapidixError) as exc:
            await client.search_series("x")
        assert exc.value.code == "NOT_CONFIGURED"

    import asyncio

    asyncio.run(_run())


def test_search_accepts_envelope_variants():
    import asyncio

    variants = [
        {"data": [{"id": "b1", "title": "A"}]},
        {"results": [{"book_id": "b2", "name": "B"}]},
        [{"series_id": "b3", "title": "C"}],
        {"dramas": {"list": [{"sid": "b4", "book_title": "D"}]}},
    ]
    for payload in variants:
        def handler(req, _p=payload):
            return httpx.Response(200, json=_p)

        async def _go():
            client = make_client(transport=httpx.MockTransport(handler))
            return await client.search_series("love")

        out = asyncio.run(_go())
        assert len(out) == 1 and out[0].external_series_id.startswith("b")


def test_normalize_episode_aliases_and_fallback_number():
    ep = normalize_episode("rapidix", {"chapter_id": "c9", "chapter_number": "7"})
    assert ep.external_episode_id == "c9"
    assert ep.episode_number == 7
    ep2 = normalize_episode("rapidix", {"id": "e1"}, fallback_number=3)
    assert ep2.episode_number == 3
    with pytest.raises(ValueError):
        normalize_episode("rapidix", {"id": "e2"})


def test_episodes_pagination_cursor_shapes():
    import asyncio

    calls: list = []

    import json as _json

    def handler(req: httpx.Request) -> httpx.Response:
        body = _json.loads(req.content.decode())
        assert req.method == "POST"
        assert body.get("id") == "b1"
        calls.append(body)
        if len(calls) == 1:
            return httpx.Response(200, json={
                "episodes": [{"id": "e1", "episode_number": 1}],
                "has_more": True, "max_cursor": "abc123",
            })
        return httpx.Response(200, json={
            "data": {"episodes": [{"id": "e2", "episode_number": 2}]},
        })

    async def _go():
        client = make_client(transport=httpx.MockTransport(handler))
        p1 = await client.list_episodes("b1")
        assert isinstance(p1, EpisodePage)
        assert p1.has_more is True and p1.next_cursor == "abc123"
        p2 = await client.list_episodes("b1", cursor=p1.next_cursor)
        assert [e.episode_number for e in p2.episodes] == [2]
        assert p2.has_more is False

    asyncio.run(_go())
    assert len(calls) == 2


def test_429_retries_then_succeeds():
    import asyncio

    attempts = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(429, json={"message": "too fast"})
        return httpx.Response(200, json={"episodes": []})

    async def _go():
        client = make_client(transport=httpx.MockTransport(handler))
        page = await client.list_episodes("b1")
        assert page.episodes == []

    asyncio.run(_go())
    assert attempts["n"] == 3


def test_auth_failure_has_no_retry_and_no_key_in_error():
    import asyncio

    attempts = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(401, json={"message": "nope"})

    async def _go():
        client = make_client(transport=httpx.MockTransport(handler))
        with pytest.raises(RapidixError) as exc:
            await client.list_episodes("b1")
        assert exc.value.code == "AUTH_FAILED"
        assert "test_rapidix_key" not in str(exc.value)

    asyncio.run(_go())
    assert attempts["n"] == 1


def test_timeout_maps_typed():
    import asyncio

    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=req)

    async def _go():
        client = make_client(transport=httpx.MockTransport(handler))
        with pytest.raises(RapidixError) as exc:
            await client.list_episodes("b1")
        assert exc.value.code in ("TIMEOUT", "TEMPORARY")

    asyncio.run(_go())


def test_redact_strips_key_material():
    red = _redact({"x-rapidapi-key": "SECRETVALUE123", "q": "love"})
    assert red == {"x-rapidapi-key": "<redacted>", "q": "love"}
    red2 = _redact("https://h/p?api-key=SECRETVALUE12345678901234567890")
    assert "SECRETVALUE" not in red2
