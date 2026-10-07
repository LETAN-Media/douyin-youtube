"""Tests for Drama Movie Discovery service & route.

Covers:
- NetShort feed discovery contract
- ShortMax feed discovery contract (/shortmax/api/v1/feed/ranked with fallback to home)
- Multi-provider feed discovery aggregation (empty query)
- Keyword search aggregation (non-empty query)
- Resilience: one provider failing does not fail discovery
- Resilience: all providers failing returns errors list and empty items
- Persistent Last-Known-Good (LKG) cache fallback (stale=True, source='cache')
- Ephemeral guarantee: discovery does not write to drama_series
- Import flow: series only enters DB when imported as source and scanned
- Real sanitized response envelope shapes regression tests
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db import client as dbc
from app.db.repositories import drama as repo
from app.main import create_app
from app.models.drama import normalize_series
from app.services.discovery import (
    clear_discovery_cache,
    discover_movies,
)
from app.services.providers import get_provider
from app.services.providers import pool as pool_mod
from app.services.providers.base import ProviderError, RapidApiProvider

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
        assert req.url.path == "/shortmax/api/v1/feed/ranked"
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


def test_payload_list_regression_shapes():
    # 1. Rapidix shape
    rapidix_data = {
        "status": "success",
        "total": 1,
        "data": [
            {
                "id": "65df8281",
                "title": "Cintai aku",
                "image": "https://img/poster.jpg",
                "episodes": 68,
                "description": "Synopsis...",
            }
        ],
    }
    items = RapidApiProvider._payload_list(rapidix_data)
    assert len(items) == 1
    norm = normalize_series("rapidix", items[0])
    assert norm.external_series_id == "65df8281"
    assert norm.title == "Cintai aku"
    assert norm.thumbnail_url == "https://img/poster.jpg"
    assert norm.total_episodes == 68

    # 2. Nested result.list shape
    nested_data = {
        "result": {
            "list": [{"id": "item1", "title": "Drama 1"}]
        }
    }
    assert len(RapidApiProvider._payload_list(nested_data)) == 1

    # 3. Direct list
    assert len(RapidApiProvider._payload_list([{"id": "item2"}])) == 1


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
    assert res1["source"] == "live"
    assert res1["stale"] is False
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
    assert res["source"] == "live"
    assert res["stale"] is False
    assert res["providers"]["netshort"]["status"] == "ok"
    assert res["providers"]["shortmax"]["status"] == "rate_limited"
    assert any(err["provider"] == "shortmax" and err["status"] == "rate_limited" for err in res["errors"])


def test_discover_all_providers_failing_with_no_cache_returns_clean_response(db, monkeypatch):
    from app.services.discovery import clear_discovery_cache

    clear_discovery_cache()

    async def fake_execute(provider_name, op, **kwargs):
        raise ProviderError("AUTH_FAILED", "Bad key")

    import asyncio
    monkeypatch.setattr(pool_mod, "execute", fake_execute)

    res = asyncio.run(discover_movies(provider="all", query="", limit=10))
    assert res["items"] == []
    assert len(res["errors"]) >= 1
    assert res["source"] == "live"
    assert res["stale"] is False


def test_discover_lkg_cache_fallback_when_upstreams_fail(db, monkeypatch):
    # Pre-populate LKG cache
    repo.upsert_discovery_cache_items([
        {
            "provider": "netshort",
            "external_series_id": "lkg_101",
            "title": "Cached LKG Series",
            "thumbnail_url": "https://img/lkg.jpg",
            "total_episodes": 40,
        }
    ])

    # Simulate all live upstreams failing
    async def fake_execute(provider_name, op, **kwargs):
        raise ProviderError("TEMPORARY", "502 upstream unreachable")

    import asyncio
    monkeypatch.setattr(pool_mod, "execute", fake_execute)

    res = asyncio.run(discover_movies(provider="all", query="", limit=10))
    assert len(res["items"]) == 1
    assert res["items"][0]["external_series_id"] == "lkg_101"
    assert res["items"][0]["title"] == "Cached LKG Series"
    assert res["source"] == "cache"
    assert res["stale"] is True
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


def test_discover_does_not_persist_to_drama_series(db):
    c = _client()

    # Pre-check: database has 0 series
    db_cli = dbc.get_client()
    pre_count = db_cli.execute("SELECT count(*) as c FROM drama_series").fetchone()["c"]
    assert pre_count == 0

    # Execute discovery via route
    r = c.get("/api/drama/discover?provider=all&limit=20", headers=ADMIN)
    assert r.status_code == 200

    # Post-check: database STILL has 0 series in drama_series
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


def test_normalize_provider_error_mapping():
    from app.services.discovery import normalize_provider_error

    err_rate = normalize_provider_error("shortmax", "RATE_LIMITED")
    assert err_rate["status"] == "rate_limited"
    assert err_rate["retryable"] is True
    assert "giới hạn tần suất" in err_rate["message"]

    err_outage = normalize_provider_error("netshort", "ALL_PROVIDERS_FAILED")
    assert err_outage["status"] == "temporarily_unavailable"
    assert err_outage["retryable"] is True
    assert "tạm thời không khả dụng" in err_outage["message"]

    err_vendor = normalize_provider_error("starshort", "VENDOR_DOWN")
    assert err_vendor["status"] == "temporarily_unavailable"
    assert err_vendor["retryable"] is True

    err_unsupported = normalize_provider_error("rapidix", "UNSUPPORTED")
    assert err_unsupported["status"] == "not_supported"
    assert err_unsupported["retryable"] is False

    err_auth = normalize_provider_error("dramabox", "AUTH_FAILED")
    assert err_auth["status"] == "upstream_error"
    assert err_auth["retryable"] is False


def test_discovery_route_returns_typed_public_diagnostics(monkeypatch):
    c = _client()

    async def fake_execute(provider_name, op, **kwargs):
        from app.models.drama import NormalizedSeries
        if provider_name == "shortmax":
            raise ProviderError("TEMPORARY", "502 Bad Gateway", http_status=502)
        elif provider_name == "netshort":
            return [
                NormalizedSeries(provider="netshort", external_series_id="ns_live", title="Live NetShort", total_episodes=50)
            ], "netshort_hub"
        return [], "hub"

    monkeypatch.setattr(pool_mod, "execute", fake_execute)

    r = c.get("/api/drama/discover?provider=all&limit=20", headers=ADMIN)
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["title"] == "Live NetShort"

    # errors list must contain normalized typed structure
    assert len(data["errors"]) == 1
    err = data["errors"][0]
    assert err["provider"] == "shortmax"
    assert err["status"] == "temporarily_unavailable"
    assert err["retryable"] is True
    assert err["message"] == "Nguồn phim tạm thời không khả dụng."
