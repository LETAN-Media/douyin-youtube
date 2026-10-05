"""Publisher failure paths must never orphan reels/publications.

Regression tests for the Funlife1236 incident: two queue jobs failed where
the publication stayed 'queued' and the reels bricked at 'processing' —
invisible to the scheduler (wants 'new') and to later publisher runs
(wants queue rows). Flow showed publisher gray idle with videos queued.

- Past/invalid publishAt fails loudly as SLOT_MISSED (typed, persisted).
- Uncaught worker errors fail the publication and release the reel.
- The orphan sweep heals stuck claims but never touches live jobs.

No YouTube, no downloads: SLOT_MISSED triggers before any media work.
"""

import asyncio
import json
import os
from pathlib import Path

import app.db.client as client_module
from app.config import settings
from app.db.client import migrate
from app.db.repositories import (
    ai_metadata,
    ai_settings,
    destinations,
    pipelines,
    publications,
    publish_queue,
    reels,
    sources,
    youtube_auth,
)
from app.services.facebook_global_publisher import (
    _handle_unexpected_job_error,
    run_publisher_once,
)

TEST_DB_PATH = Path("/tmp/backend_facebook_publisher_recovery_test.db")
TEST_DB_URL = f"file:{TEST_DB_PATH}"
ADMIN = "test_admin_token"

CREDS_JSON = json.dumps({
    "token": "ya29.test",
    "refresh_token": "rt_test",
    "token_uri": "https://oauth2.googleapis.com/token",
    "client_id": "cid",
    "client_secret": "csecret",
    "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
})

_PREV_SETTINGS: dict = {}
_PREV_ENV: dict = {}
_KEYS = (
    "ADMIN_TOKEN", "TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN",
    "TOOLNET_BASE_URL", "TOOLNET_API_KEY", "TOOLNET_MODEL", "TOOLNET_AI_ENABLED",
)


def setup_function(_func=None) -> None:
    _PREV_SETTINGS.clear()
    _PREV_ENV.clear()
    for key in _KEYS:
        _PREV_SETTINGS[key] = getattr(settings, key)
        _PREV_ENV[key] = os.environ.get(key)
    client_module._client = None
    os.environ["ADMIN_TOKEN"] = ADMIN
    os.environ["TURSO_DATABASE_URL"] = TEST_DB_URL
    os.environ["TURSO_AUTH_TOKEN"] = "test_token"
    settings.ADMIN_TOKEN = ADMIN
    settings.TURSO_DATABASE_URL = TEST_DB_URL
    settings.TURSO_AUTH_TOKEN = "test_token"
    settings.TOOLNET_BASE_URL = "https://toolnet.example.com/v1"
    settings.TOOLNET_API_KEY = "test_toolnet_key"
    settings.TOOLNET_MODEL = "test-model-v1"
    settings.TOOLNET_AI_ENABLED = True
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


def seed_connected(pipe_id: str = "pl_rec", did: str = "ytd_rec") -> tuple[str, str]:
    async def _go():
        await pipelines.create_pipeline(pipeline_id=pipe_id, name="R", slug=pipe_id)
        await sources.create_source(
            source_id=f"{pipe_id}_src", pipeline_id=pipe_id, page_id="111",
            reels_url="https://www.facebook.com/111/reels/",
        )
        await destinations.create_destination(
            destination_id=did, pipeline_id=pipe_id,
            channel_id="UC_TEST", channel_name="Test Chan",
            visibility="public", enabled=True,
        )
        await destinations.set_connected(did, channel_id="UC_TEST", channel_name="Test Chan")
        await youtube_auth.save_credentials(did, CREDS_JSON)

    asyncio.run(_go())
    return pipe_id, did


def seed_ready_reel(pipe_id: str, rid: str, caption: str = "Caption đầy đủ cho kiểm thử phục hồi") -> str:
    """Reel with generated metadata matching the canonical hash."""
    reel_db_id = f"{pipe_id}_{rid}"

    async def _go():
        await reels.insert_reel_if_new(
            reel_db_id=reel_db_id, source_id=f"{pipe_id}_src", reel_id=rid,
            reel_url=f"https://www.facebook.com/reel/{rid}/", caption=caption,
        )
        _, config_hash = await ai_settings.current_config_hash(pipe_id)
        await ai_metadata.upsert_generated(
            reel_db_id=reel_db_id,
            title="Tiêu đề kiểm thử phục hồi",
            description="Mô tả kiểm thử.",
            hashtags=["#a", "#b", "#c"],
            model=settings.TOOLNET_MODEL,
            source_hash=ai_metadata.source_hash(caption, rid),
            config_hash=config_hash,
        )

    asyncio.run(_go())
    return reel_db_id


def test_past_publish_at_fails_slot_missed_not_orphan() -> None:
    """A job claimed after its slot passed must fail SLOT_MISSED with the
    publication marked and the reel released — never orphaned."""
    pipe_id, did = seed_connected()
    reel_db_id = seed_ready_reel(pipe_id, "r1")
    pub_id = "pub_slot_missed"

    async def _stage():
        assert await reels.advance_status(reel_db_id, "new", "queued")
        pub, _ = await publications.get_or_create(
            publication_id=pub_id, reel_db_id=reel_db_id, destination_id=did
        )
        assert pub["status"] == "queued"
        await publications.set_scheduled_publish_at(pub_id, "2020-01-01T00:00:00Z")
        await publish_queue.enqueue_publish_job(
            pipeline_id=pipe_id, destination_id=did,
            reel_db_id=reel_db_id, publication_id=pub_id,
        )

    asyncio.run(_stage())

    result = asyncio.run(run_publisher_once())

    assert result is not None and result.get("error_code") == "SLOT_MISSED", result

    async def _check():
        pub = await publications.get_publication(pub_id)
        assert pub is not None and pub["status"] == "failed"
        assert "SLOT_MISSED" in (pub.get("last_error") or "")
        reel = await reels.get_reel(reel_db_id)
        assert reel is not None and reel["status"] == "new"

    asyncio.run(_check())


def test_orphan_sweep_heals_stuck_processing() -> None:
    """Production shape: reel bricked at 'processing', queue job terminal,
    publication phantom 'queued' → sweep releases the reel and fails the
    publication with a clear code."""
    pipe_id, did = seed_connected("pl_rec2", "ytd_rec2")
    reel_db_id = seed_ready_reel("pl_rec2", "r1")
    pub_id = "pub_orphan"

    async def _stage():
        assert await reels.advance_status(reel_db_id, "new", "queued")
        await publications.get_or_create(
            publication_id=pub_id, reel_db_id=reel_db_id, destination_id=did
        )
        qid = await publish_queue.enqueue_publish_job(
            pipeline_id=pipe_id, destination_id=did,
            reel_db_id=reel_db_id, publication_id=pub_id,
        )
        # Worker died mid-flight: queue terminal, reel still claimed.
        await publish_queue.update_job_status(qid, "failed", stage="error",
                                              error_code="BOOM", error="boom")
        assert await reels.advance_status(reel_db_id, "queued", "processing")

    asyncio.run(_stage())

    healed = asyncio.run(reels.recover_orphaned_reel_claims())
    assert healed == 1

    async def _check():
        reel = await reels.get_reel(reel_db_id)
        assert reel is not None and reel["status"] == "new"
        pub = await publications.get_publication(pub_id)
        assert pub is not None and pub["status"] == "failed"
        assert "ORPHANED_JOB_FAILED" in (pub.get("last_error") or "")

    asyncio.run(_check())


def test_orphan_sweep_never_touches_live_jobs() -> None:
    """A reel with a live queued job is processing legitimately — hands off."""
    pipe_id, did = seed_connected("pl_rec3", "ytd_rec3")
    reel_db_id = seed_ready_reel("pl_rec3", "r1")

    async def _stage():
        assert await reels.advance_status(reel_db_id, "new", "queued")
        await publications.get_or_create(
            publication_id="pub_live", reel_db_id=reel_db_id, destination_id=did
        )
        await publish_queue.enqueue_publish_job(
            pipeline_id=pipe_id, destination_id=did,
            reel_db_id=reel_db_id, publication_id="pub_live",
        )
        assert await reels.advance_status(reel_db_id, "queued", "processing")

    asyncio.run(_stage())

    healed = asyncio.run(reels.recover_orphaned_reel_claims())
    assert healed == 0

    async def _check():
        reel = await reels.get_reel(reel_db_id)
        assert reel is not None and reel["status"] == "processing"
        pub = await publications.get_publication("pub_live")
        assert pub is not None and pub["status"] == "queued"

    asyncio.run(_check())


def test_unexpected_handler_fails_publication_and_releases_reel() -> None:
    """Errors escaping _process_one_job must not orphan anything."""
    pipe_id, did = seed_connected("pl_rec4", "ytd_rec4")
    reel_db_id = seed_ready_reel("pl_rec4", "r1")

    async def _stage():
        assert await reels.advance_status(reel_db_id, "new", "queued")
        await publications.get_or_create(
            publication_id="pub_unexp", reel_db_id=reel_db_id, destination_id=did
        )
        assert await reels.advance_status(reel_db_id, "queued", "processing")

    asyncio.run(_stage())

    asyncio.run(_handle_unexpected_job_error(
        {"id": "pq_missing", "publication_id": "pub_unexp", "reel_db_id": reel_db_id},
        RuntimeError("boom"),
    ))

    async def _check():
        pub = await publications.get_publication("pub_unexp")
        assert pub is not None and pub["status"] == "failed"
        assert "UNEXPECTED" in (pub.get("last_error") or "")
        reel = await reels.get_reel(reel_db_id)
        assert reel is not None and reel["status"] == "new"

    asyncio.run(_check())
