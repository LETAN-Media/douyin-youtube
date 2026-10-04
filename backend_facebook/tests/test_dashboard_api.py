import asyncio
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.db.client as client_module
from app.config import settings
from app.db.client import migrate
from app.db.repositories import destinations, pipelines, publications, reels, sources
from app.main import create_app

TEST_DB_PATH = Path("/tmp/backend_facebook_dashboard_test.db")
TEST_DB_URL = f"file:{TEST_DB_PATH}"


def fresh_db() -> None:
    client_module._client = None
    os.environ["ADMIN_TOKEN"] = "test_admin_token"
    os.environ["TURSO_DATABASE_URL"] = TEST_DB_URL
    os.environ["TURSO_AUTH_TOKEN"] = "test_token"
    settings.ADMIN_TOKEN = "test_admin_token"
    settings.TURSO_DATABASE_URL = TEST_DB_URL
    settings.TURSO_AUTH_TOKEN = "test_token"
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    for suffix in ("-wal", "-shm", "-journal"):
        p = Path(str(TEST_DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    asyncio.run(migrate())


@pytest.fixture()
def db():
    prev_url = os.environ.get("TURSO_DATABASE_URL")
    prev_settings = settings.TURSO_DATABASE_URL
    fresh_db()
    yield
    client_module._client = None
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    if prev_url is not None:
        os.environ["TURSO_DATABASE_URL"] = prev_url
    settings.TURSO_DATABASE_URL = prev_settings
    client_module._client = None


def _run(coro):
    return asyncio.run(coro)


def _seed() -> dict:
    async def _go():
        await pipelines.create_pipeline(pipeline_id="pl_d", name="Dash", slug="pl_d")
        await sources.create_source(
            source_id="src_d", pipeline_id="pl_d", page_id="999",
            page_name="Real Page", reels_url="https://www.facebook.com/999/reels/",
        )
        await reels.insert_reel_if_new(
            reel_db_id="reel_d1", source_id="src_d", reel_id="fb1",
            reel_url="https://www.facebook.com/reel/1/",
        )
        await destinations.create_destination(
            destination_id="ytd_d", pipeline_id="pl_d",
            channel_id="UC_REAL", channel_name="Real Chan",
        )
        await destinations.set_connected("ytd_d", channel_id="UC_REAL", channel_name="Real Chan")
        await publications.create_publication(
            publication_id="pub_d", reel_db_id="reel_d1", destination_id="ytd_d",
            status="published",
        )
        await publications.mark_published("pub_d", "yt_real_1")
        await reels.mark_reel_published("reel_d1", "yt_real_1")
        return True

    return _run(_go())


def test_pipelines_list(db) -> None:
    _seed()
    r = TestClient(create_app()).get("/api/facebook/pipelines")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list) and len(body) == 1
    assert body[0]["id"] == "pl_d"
    assert set(("id", "name", "slug", "enabled", "auto_publish")) <= set(body[0].keys())


def test_summary_aggregate(db) -> None:
    _seed()
    r = TestClient(create_app()).get("/api/facebook/pipelines/pl_d/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["pipeline"]["id"] == "pl_d"
    assert body["sources"] == 1
    assert body["inventory"] == 1
    assert body["destinations"] == 1
    assert body["published"] == 1
    assert body["failed"] == 0


def test_summary_404(db) -> None:
    r = TestClient(create_app()).get("/api/facebook/pipelines/nope/summary")
    assert r.status_code == 404


def test_publications_pipeline_join(db) -> None:
    _seed()
    r = TestClient(create_app()).get("/api/facebook/pipelines/pl_d/publications")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["reel_id"] == "fb1"
    assert item["channel_name"] == "Real Chan"
    assert item["youtube_video_id"] == "yt_real_1"
    assert item["status"] == "published"
    blob = r.text
    assert "refresh_token" not in blob and "credentials" not in blob


def test_publications_404(db) -> None:
    r = TestClient(create_app()).get("/api/facebook/pipelines/nope/publications")
    assert r.status_code == 404


def test_sources_real_fields(db) -> None:
    _seed()
    r = TestClient(create_app()).get("/api/facebook/pipelines/pl_d/sources")
    assert r.status_code == 200
    item = r.json()[0]
    assert item["page_id"] == "999"
    assert item["page_name"] == "Real Page"
    assert "discovered_total" in item and "last_scan_status" in item
