"""Tests for Drama Movie Discovery service & route.

Covers:
- NetShort feed discovery contract
- ShortMax feed discovery contract
- Multi-provider feed discovery aggregation (empty query)
- Keyword search aggregation (non-empty query)
- Resilience: one provider failing does not fail discovery
- Resilience: all providers failing returns errors list and empty items
- In-memory cache behavior
- Ephemeral guarantee: discovery does not write to the database
- Import flow: series only enters DB when imported as source and scanned
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db import client as dbc
from app.db.repositories import drama as repo
from app.main import create_app
from app.services.discovery import (
    clear_discovery_cache,
    discover_movies,
)
from app.services.providers import get_provider
from app.services.providers import pool as pool_mod
from app.services.providers.base import ProviderError

ADMIN = {"X-Admin-Token": "test_admin_token"}


def _client():
    return TestClient(create_app())


@pytest.fixture(autouse=True)
def _reset_discovery_state():
    clear_discovery_cache()
    yield
    clear_discovery_cache()


def test_netshort_discover_series_feed():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/netshort/api/v1/feed/1"
        assert req.url.params.get("lang") == "en"
        return httpx.Response(200, json={
            "list": [
                {"id": "ns_101", "title": "NetShort Drama 1", "cover": "https://img/1.jpg", "total": 60},
                {"id": "ns_102", "title": "NetShort Drama 2", "cover": "https://img/2.jpg", "total": 45},
            ]
        })

    import asyncio
    p = get_provider("netshort", transport=httpx.MockTransport(handler))
    series = asyncio.run(p.discover_series(limit=10))
    assert len(series) == 2
    assert series[0].external_series_id == "ns_101"
    assert series[0].title == "NetShort Drama 1"
    assert series[0].total_episodes == 60


def test_shortmax_discover_series_feed():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/shortmax/api/v1/feed/foryou"
        assert req.url.params.get("lang") == "en"
        return httpx.Response(200, json={
            "data": [
                {"bookId": "sm_201", "title": "ShortMax Drama 1", "cover": "https://img/sm1.jpg", "episode_count": 50},
            ]
        })

    import asyncio
    p = get_provider("shortmax", transport=httpx.MockTransport(handler))
    series = asyncio.run(p.discover_series(limit=10))
    assert len(series) == 1
    assert series[0].external_series_id == "sm_201"
    assert series[0].title == "ShortMax Drama 1"
    assert series[0].total_episodes == 50


def test_discover_service_aggregation_and_cache(monkeypatch):
    calls = {"netshort": 0, "shortmax": 0}

    async def fake_execute(provider_name, op, **kwargs):
        calls[provider_name] = calls.get(provider_name, 0) + 1
        from app.models.drama import NormalizedSeries
        if provider_name == "netshort":
            return [
                NormalizedSeries(provider="netshort", external_series_id="ns1", title="NS Show", total_episodes=10)
            ], "netshort_hub"
        elif provider_name == "shortmax":
            return [
                NormalizedSeries(provider="shortmax", external_series_id="sm1", title="SM Show", total_episodes=20)
            ], "shortmax_hub"
        raise ProviderError("UNSUPPORTED", "not supported")

    import asyncio
    monkeypatch.setattr(pool_mod, "execute", fake_execute)

    res1 = asyncio.run(discover_movies(provider="all", query="", limit=10))
    assert len(res1["items"]) == 2
    assert {i["provider"] for i in res1["items"]} == {"netshort", "shortmax"}
    assert calls["netshort"] == 1
    assert calls["shortmax"] == 1

    # Second call hits cache; execute should not be called again
    res2 = asyncio.run(discover_movies(provider="all", query="", limit=10))
    assert res2 == res1
    assert calls["netshort"] == 1
    assert calls["shortmax"] == 1


def test_discover_one_provider_failure_does_not_break_all(monkeypatch):
    async def fake_execute(provider_name, op, **kwargs):
        from app.models.drama import NormalizedSeries
        if provider_name == "netshort":
            return [
                NormalizedSeries(provider="netshort", external_series_id="ns1", title="NS Show")
            ], "netshort_hub"
        raise ProviderError("RATE_LIMITED", "netshort ok, shortmax 429")

    import asyncio
    monkeypatch.setattr(pool_mod, "execute", fake_execute)

    res = asyncio.run(discover_movies(provider="all", query="", limit=10))
    assert len(res["items"]) == 1
    assert res["items"][0]["external_series_id"] == "ns1"
    assert res["providers"]["netshort"]["status"] == "ok"
    assert res["providers"]["shortmax"]["status"] == "error"
    assert any(err["provider"] == "shortmax" for err in res["errors"])


def test_discover_all_providers_failing_returns_clean_response(monkeypatch):
    async def fake_execute(provider_name, op, **kwargs):
        raise ProviderError("AUTH_FAILED", "Bad key")

    import asyncio
    monkeypatch.setattr(pool_mod, "execute", fake_execute)

    res = asyncio.run(discover_movies(provider="all", query="", limit=10))
    assert res["items"] == []
    assert len(res["errors"]) >= 1


def test_discover_keyword_search_routes_to_search_providers(monkeypatch):
    queried_providers = []

    async def fake_execute(provider_name, op, **kwargs):
        queried_providers.append((provider_name, op, kwargs.get("query")))
        from app.models.drama import NormalizedSeries
        if provider_name == "starshort":
            return [
                NormalizedSeries(provider="starshort", external_series_id="ss1", title="Star Boss")
            ], "starshort_upstream"
        return [], "upstream"

    import asyncio
    monkeypatch.setattr(pool_mod, "execute", fake_execute)

    res = asyncio.run(discover_movies(provider="all", query="boss", limit=10))
    assert any(p == "starshort" and op == "search_series" and q == "boss" for p, op, q in queried_providers)
    assert len(res["items"]) == 1
    assert res["items"][0]["title"] == "Star Boss"


def test_discover_does_not_persist_to_database(db):
    c = _client()

    # Pre-check: database has 0 series
    db_cli = dbc.get_client()
    pre_count = db_cli.execute("SELECT count(*) as c FROM drama_series").fetchone()["c"]
    assert pre_count == 0

    # Execute discovery via route
    r = c.get("/api/drama/discover?provider=all&limit=20", headers=ADMIN)
    assert r.status_code == 200

    # Post-check: database STILL has 0 series
    post_count = db_cli.execute("SELECT count(*) as c FROM drama_series").fetchone()["c"]
    assert post_count == 0


def test_import_flow_persists_only_after_scan(db, monkeypatch):
    c = _client()

    # 1. Create a pipeline
    p = repo.create_pipeline(name="My Imported Pipeline")

    # 2. Add source from discovery item
    s = c.post(
        f"/api/drama/pipelines/{p['id']}/sources",
        headers=ADMIN,
        json={
            "provider": "starshort",
            "external_series_id": "ss_import_99",
            "name": "Imported Boss Drama",
        },
    )
    assert s.status_code == 201
    source_id = s.json()["id"]

    # At this point, source exists, but series has not been scanned/upserted yet
    db_cli = dbc.get_client()
    count_before_scan = db_cli.execute("SELECT count(*) as c FROM drama_series WHERE source_id = ?", (source_id,)).fetchone()["c"]
    assert count_before_scan == 0

    # Mock pool for scan_source
    async def fake_execute(provider_name, op, **kwargs):
        from app.models.drama import EpisodePage, NormalizedEpisode, NormalizedSeries
        if op == "get_series":
            return NormalizedSeries(provider="starshort", external_series_id="ss_import_99", title="Imported Boss Drama", total_episodes=2), "upstream"
        elif op == "list_episodes":
            return EpisodePage(episodes=[
                NormalizedEpisode(provider="starshort", external_episode_id="ep1", episode_number=1, title="Episode 1"),
                NormalizedEpisode(provider="starshort", external_episode_id="ep2", episode_number=2, title="Episode 2"),
            ]), "upstream"
        return None, "upstream"

    monkeypatch.setattr(pool_mod, "execute", fake_execute)

    # 3. Trigger scan
    scan_res = c.post(f"/api/drama/sources/{source_id}/scan", headers=ADMIN)
    assert scan_res.status_code == 200
    assert scan_res.json()["episodes_found"] == 2

    # Now database has the series and inventory
    count_after_scan = db_cli.execute("SELECT count(*) as c FROM drama_series WHERE source_id = ?", (source_id,)).fetchone()["c"]
    assert count_after_scan == 1

    inv = c.get(f"/api/drama/pipelines/{p['id']}/inventory", headers=ADMIN).json()
    assert inv["total"] == 2
    assert [e["episode_number"] for e in inv["items"]] == [1, 2]
