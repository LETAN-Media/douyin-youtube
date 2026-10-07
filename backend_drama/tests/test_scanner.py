"""Scanner with a mocked provider: initial + incremental + pagination."""

import asyncio

from app.db.repositories import drama as repo
from app.models.drama import EpisodePage, NormalizedEpisode
from app.services.rapidix import RapidixError
from app.services.scanner import scan_source


class FakeClient:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = 0

    async def list_episodes(self, external_series_id, cursor=None):
        self.calls += 1
        for page in self.pages:
            if page.get("cursor_in") == cursor:
                eps = [
                    NormalizedEpisode(
                        provider="rapidix", external_episode_id=e["id"],
                        episode_number=e["n"], title=e.get("t"),
                    )
                    for e in page["episodes"]
                ]
                return EpisodePage(
                    episodes=eps, next_cursor=page.get("cursor_out"),
                    has_more=page.get("has_more", False),
                )
        return EpisodePage(episodes=[], next_cursor=None, has_more=False)


def _seed(db):
    p = repo.create_pipeline(name="Scan Show")
    src = repo.create_source(pipeline_id=p["id"], external_series_id="b9")
    return p, src


def test_initial_scan_inserts_all(db):
    _, src = _seed(db)
    pages = [
        {"cursor_in": None, "episodes": [{"id": f"e{i}", "n": i} for i in (1, 2)],
         "cursor_out": "c1", "has_more": True},
        {"cursor_in": "c1", "episodes": [{"id": "e3", "n": 3}],
         "cursor_out": None, "has_more": False},
    ]
    out = asyncio.run(scan_source(src["id"], client=FakeClient(pages)))
    assert out["series_found"] == 1
    assert out["episodes_found"] == 3
    assert out["inserted"] == 3 and out["existing"] == 0
    items, total = repo.list_episodes(out["series_id"])
    assert total == 3
    assert [e["episode_number"] for e in items] == [1, 2, 3]


def test_incremental_scan_only_new(db):
    _, src = _seed(db)
    first = [{"cursor_in": None,
              "episodes": [{"id": "e1", "n": 1}, {"id": "e2", "n": 2}],
              "cursor_out": None, "has_more": False}]
    r1 = asyncio.run(scan_source(src["id"], client=FakeClient(first)))
    assert r1["inserted"] == 2
    second = [{"cursor_in": None,
               "episodes": [{"id": "e1", "n": 1}, {"id": "e2", "n": 2},
                            {"id": "e3", "n": 3}],
               "cursor_out": None, "has_more": False}]
    r2 = asyncio.run(scan_source(src["id"], client=FakeClient(second)))
    assert r2["inserted"] == 1 and r2["existing"] == 2
    assert r2["episodes_found"] == 3


def test_scan_without_series_id_refuses(db):
    p = repo.create_pipeline(name="No ID")
    src = repo.create_source(pipeline_id=p["id"])
    try:
        asyncio.run(scan_source(src["id"], client=FakeClient([])))
        raise AssertionError("expected failure")
    except RapidixError as exc:
        assert exc.code == "NOT_CONFIGURED"


def test_scan_missing_source_404_shape(db):
    try:
        asyncio.run(scan_source("dsrc_nope", client=FakeClient([])))
        raise AssertionError("expected failure")
    except ValueError as exc:
        assert "Source not found" in str(exc)


# ---------- import-scan contract: dedupe, retry-reuse, persistence ----------


def test_duplicate_import_reuses_source_row(db):
    from app.db import client as dbc

    p = repo.create_pipeline(name="Dedupe Show")
    first = repo.create_source(
        pipeline_id=p["id"], provider="rapidix",
        external_series_id="6a86d7f75eaf4433d8020a8e",
        name="Gelombang Sentuhan Terlarang",
    )
    second = repo.create_source(
        pipeline_id=p["id"], provider="rapidix",
        external_series_id="6a86d7f75eaf4433d8020a8e",
        name="Gelombang Sentuhan Terlarang",
    )
    assert first["id"] == second["id"]
    rows = dbc.get_client().execute(
        "SELECT COUNT(*) FROM drama_sources WHERE pipeline_id = ? AND provider = ? "
        "AND external_series_id = ?",
        (p["id"], "rapidix", "6a86d7f75eaf4433d8020a8e"),
    ).fetchone()
    assert rows[0] == 1


def test_scan_failure_retry_reuses_source(db):
    from app.services.rapidix import RapidixError as _RapidixError

    p = repo.create_pipeline(name="Retry Show")
    src = repo.create_source(
        pipeline_id=p["id"], provider="rapidix",
        external_series_id="6a86d7f75eaf4433d8020a8e",
        name="Gelombang Sentuhan Terlarang",
    )

    class FailClient:
        async def list_episodes(self, external_series_id, cursor=None):
            raise _RapidixError("RAPIDIX_UPSTREAM_ERROR", "boom")

    try:
        asyncio.run(scan_source(src["id"], client=FailClient()))
        raise AssertionError("expected failure")
    except _RapidixError:
        pass
    # Retry path reuses the same source row (no orphan duplicate).
    again = repo.create_source(
        pipeline_id=p["id"], provider="rapidix",
        external_series_id="6a86d7f75eaf4433d8020a8e",
        name="Gelombang Sentuhan Terlarang",
    )
    assert again["id"] == src["id"]

    pages = [{"cursor_in": None,
              "episodes": [{"id": "e1", "n": 1}, {"id": "e2", "n": 2}],
              "cursor_out": None, "has_more": False}]

    class OkClient(FailClient):
        def __init__(self, pages):
            self.pages = pages

        async def list_episodes(self, external_series_id, cursor=None):
            eps = [
                NormalizedEpisode(
                    provider="rapidix", external_episode_id=e["id"],
                    episode_number=e["n"], title=e.get("t"),
                )
                for e in self.pages[0]["episodes"]
            ]
            return EpisodePage(episodes=eps, next_cursor=None, has_more=False)

    out = asyncio.run(scan_source(src["id"], client=OkClient(pages)))
    assert out["episodes_found"] == 2 and out["inserted"] == 2
    items, total = repo.list_episodes(out["series_id"])
    assert total == 2
    assert [e["episode_number"] for e in items] == [1, 2]


def test_scan_route_maps_pool_exhausted(db):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.services.providers.pool import PoolExhausted

    p = repo.create_pipeline(name="Route Codes")
    src = repo.create_source(pipeline_id=p["id"], external_series_id="abc123")

    import app.routes.sources as sources_route

    real_scan = sources_route.scan_source

    async def _raise_not_found(source_id, **kwargs):
        raise PoolExhausted("NOT_FOUND", "gone", [])

    async def _raise_all_failed(source_id, **kwargs):
        raise PoolExhausted("ALL_PROVIDERS_FAILED", "down", [])

    client = TestClient(create_app())
    sources_route.scan_source = _raise_not_found
    try:
        r = client.post(
            f"/api/drama/sources/{src['id']}/scan",
            headers={"X-Admin-Token": "test_admin_token"},
        )
        assert r.status_code == 404, r.text
        assert r.json()["detail"]["error"] == "PROVIDER_SERIES_NOT_FOUND"
    finally:
        sources_route.scan_source = real_scan
    sources_route.scan_source = _raise_all_failed
    try:
        r = client.post(
            f"/api/drama/sources/{src['id']}/scan",
            headers={"X-Admin-Token": "test_admin_token"},
        )
        assert r.status_code == 502, r.text
        assert r.json()["detail"]["error"] == "ALL_PROVIDERS_FAILED"
    finally:
        sources_route.scan_source = real_scan
