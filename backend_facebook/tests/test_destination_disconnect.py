"""Safe YouTube destination disconnect (manual publish).

- Connected destination disconnects and vanishes from the manual list.
- Credentials + pending OAuth states are deleted; history is preserved.
- Live (queued/processing) jobs block with 409 and keep credentials.
- Same channel on two pipelines: disconnecting one leaves the other alone.
"""

import asyncio
import os
from pathlib import Path

from fastapi.testclient import TestClient

import app.db.client as client_module
from app.config import settings
from app.db.client import migrate
from app.db.repositories import destinations, pipelines, sources, youtube_auth
from app.db.repositories import manual_publications as manual_repo
from app.db.repositories import publish_queue, publications
from app.main import create_app

TEST_DB_PATH = Path("/tmp/backend_facebook_disconnect_test.db")
TEST_DB_URL = f"file:{TEST_DB_PATH}"
ADMIN = "test_admin_token"
AUTH_HEADERS = {"X-Admin-Token": ADMIN}

_KEYS = ("ADMIN_TOKEN", "TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN")
_PREV_SETTINGS: dict = {}
_PREV_ENV: dict = {}


def setup_function(_func=None) -> None:
    _PREV_SETTINGS.clear()
    _PREV_ENV.clear()
    for key in _KEYS:
        _PREV_SETTINGS[key] = getattr(settings, key, None)
        _PREV_ENV[key] = os.environ.get(key)
    client_module._client = None
    os.environ["ADMIN_TOKEN"] = ADMIN
    os.environ["TURSO_DATABASE_URL"] = TEST_DB_URL
    os.environ["TURSO_AUTH_TOKEN"] = "test_token"
    settings.ADMIN_TOKEN = ADMIN
    settings.TURSO_DATABASE_URL = TEST_DB_URL
    settings.TURSO_AUTH_TOKEN = "test_token"
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    for suffix in ("-wal", "-shm", "-journal"):
        p = Path(str(TEST_DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    asyncio.run(migrate())


def teardown_function(_func=None) -> None:
    client_module._client = None
    for key, value in _PREV_SETTINGS.items():
        setattr(settings, key, value)
    for key, value in _PREV_ENV.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    _PREV_SETTINGS.clear()
    _PREV_ENV.clear()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    for suffix in ("-wal", "-shm", "-journal"):
        p = Path(str(TEST_DB_PATH) + suffix)
        if p.exists():
            p.unlink()


def seed_connected(pipe_id: str, did: str, channel: str = "Chan") -> None:
    async def _go():
        try:
            await pipelines.create_pipeline(pipeline_id=pipe_id, name=pipe_id, slug=pipe_id)
        except Exception:
            pass
        await destinations.create_destination(
            destination_id=did, pipeline_id=pipe_id, channel_id="UC_" + did,
            channel_name=channel, visibility="public", enabled=True,
        )
        await destinations.set_connected(did, channel_id="UC_" + did, channel_name=channel)
        await youtube_auth.save_credentials(did, '{"token": "x"}')
        await youtube_auth.create_oauth_state(
            state=f"st_{did}", destination_id=did, pipeline_id=pipe_id,
            expires_at="2030-01-01T00:00:00Z",
        )

    asyncio.run(_go())


def test_disconnect_hides_channel_and_deletes_secrets() -> None:
    """Cases A–D: disconnect -> gone from list, creds+states deleted,
    history intact with channel name."""
    seed_connected("pl_dc1", "ytd_dc1", "Chan One")
    client = TestClient(create_app())

    before = client.get("/api/facebook/youtube-destinations", headers=AUTH_HEADERS)
    assert before.status_code == 200 and len(before.json()) == 1

    r = client.delete(
        "/api/facebook/youtube-destinations/ytd_dc1", headers=AUTH_HEADERS
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "destination_id": "ytd_dc1", "connected": False}

    after = client.get("/api/facebook/youtube-destinations", headers=AUTH_HEADERS)
    assert after.status_code == 200 and after.json() == []

    async def _check():
        assert await youtube_auth.get_credentials("ytd_dc1") is None
        assert await youtube_auth.get_oauth_state("st_ytd_dc1") is None
        row = await destinations.get_destination("ytd_dc1")
        assert row is not None  # row kept for history
        assert row["channel_name"] == "Chan One"  # name preserved
        assert row["connected"] is False

    asyncio.run(_check())


def test_disconnect_preserves_publication_history() -> None:
    """Case D: old publications survive with resolvable channel name."""
    from app.db.repositories import reels, sources

    seed_connected("pl_dc2", "ytd_dc2", "Chan Two")

    async def _seed_pub():
        await sources.create_source(
            source_id="pl_dc2_src", pipeline_id="pl_dc2", page_id="1",
            reels_url="https://www.facebook.com/1/reels/",
        )
        await reels.insert_reel_if_new(
            reel_db_id="pl_dc2_r1", source_id="pl_dc2_src", reel_id="r1",
        )
        await publications.get_or_create(
            publication_id="pub_hist", reel_db_id="pl_dc2_r1",
            destination_id="ytd_dc2",
        )

    asyncio.run(_seed_pub())
    client = TestClient(create_app())
    r = client.delete(
        "/api/facebook/youtube-destinations/ytd_dc2", headers=AUTH_HEADERS
    )
    assert r.status_code == 200, r.text

    pubs = client.get(
        "/api/facebook/pipelines/pl_dc2/publications", headers=AUTH_HEADERS
    )
    assert pubs.status_code == 200, pubs.text
    items = pubs.json().get("items", pubs.json())
    assert any(p.get("id") == "pub_hist" for p in items)


def test_disconnect_missing_is_404() -> None:
    client = TestClient(create_app())
    r = client.delete(
        "/api/facebook/youtube-destinations/ytd_nope", headers=AUTH_HEADERS
    )
    assert r.status_code == 404, r.text


def test_disconnect_busy_auto_job_returns_409_and_keeps_creds() -> None:
    """Case E: live auto job blocks disconnect and keeps credentials."""
    seed_connected("pl_dc3", "ytd_dc3", "Chan Three")

    async def _seed_job():
        await publish_queue.enqueue_publish_job(
            pipeline_id="pl_dc3", destination_id="ytd_dc3",
            reel_db_id="pl_dc3_r1", publication_id="pub_b1",
        )

    asyncio.run(_seed_job())
    client = TestClient(create_app())
    r = client.delete(
        "/api/facebook/youtube-destinations/ytd_dc3", headers=AUTH_HEADERS
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"] == "DESTINATION_BUSY"

    async def _check():
        assert await youtube_auth.get_credentials("ytd_dc3") is not None
        row = await destinations.get_destination("ytd_dc3")
        assert row is not None and row["connected"] is True

    asyncio.run(_check())


def test_disconnect_busy_manual_job_returns_409() -> None:
    """Case E (manual): queued manual publication blocks disconnect."""
    seed_connected("pl_dc4", "ytd_dc4", "Chan Four")

    async def _seed_job():
        await manual_repo.create_manual_publication(
            destination_id="ytd_dc4", pipeline_id="pl_dc4",
            source_url="https://www.facebook.com/reel/1/",
            title="T", description="D", hashtags=[],
        )

    asyncio.run(_seed_job())
    client = TestClient(create_app())
    r = client.delete(
        "/api/facebook/youtube-destinations/ytd_dc4", headers=AUTH_HEADERS
    )
    assert r.status_code == 409, r.text


def test_disconnect_one_duplicate_leaves_the_other() -> None:
    """Case F: same channel on two pipelines disconnects independently."""
    seed_connected("pl_dc5a", "ytd_dc5a", "Same Chan")
    seed_connected("pl_dc5b", "ytd_dc5b", "Same Chan")
    client = TestClient(create_app())
    r = client.delete(
        "/api/facebook/youtube-destinations/ytd_dc5a", headers=AUTH_HEADERS
    )
    assert r.status_code == 200, r.text

    remaining = client.get("/api/facebook/youtube-destinations", headers=AUTH_HEADERS)
    assert remaining.status_code == 200
    ids = [d["id"] for d in remaining.json()]
    assert ids == ["ytd_dc5b"]

    async def _check():
        assert await youtube_auth.get_credentials("ytd_dc5b") is not None
        assert await youtube_auth.get_credentials("ytd_dc5a") is None

    asyncio.run(_check())
