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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

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
    schedules,
    sources,
    youtube_auth,
)
import app.services.facebook_global_publisher as publisher_module
from app.services.facebook_global_publisher import (
    _fail_job,
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


def test_run_once_heals_orphans_even_with_no_queued_jobs() -> None:
    """The heal step must run before the no-work exit: with an empty queue
    the loop would otherwise sleep forever and never heal the orphans."""
    pipe_id, did = seed_connected("pl_rec5", "ytd_rec5")
    reel_db_id = seed_ready_reel("pl_rec5", "r1")

    async def _stage():
        assert await reels.advance_status(reel_db_id, "new", "queued")
        await publications.get_or_create(
            publication_id="pub_orphan5", reel_db_id=reel_db_id, destination_id=did
        )
        assert await reels.advance_status(reel_db_id, "queued", "processing")

    asyncio.run(_stage())

    result = asyncio.run(run_publisher_once())
    assert result is not None and result.get("status") == "no_work", result

    async def _check():
        reel = await reels.get_reel(reel_db_id)
        assert reel is not None and reel["status"] == "new"
        pub = await publications.get_publication("pub_orphan5")
        assert pub is not None and pub["status"] == "failed"

    asyncio.run(_check())


def test_enqueue_publish_job_is_idempotent_while_active() -> None:
    """Concurrent enqueue attempts must reuse the live job, not race."""
    async def _go():
        q1 = await publish_queue.enqueue_publish_job(
            pipeline_id="pl_idem", destination_id="ytd_idem",
            reel_db_id="reel_idem", publication_id="pub_idem", priority=999,
        )
        q2 = await publish_queue.enqueue_publish_job(
            pipeline_id="pl_idem", destination_id="ytd_idem",
            reel_db_id="reel_idem", publication_id="pub_idem", priority=998,
        )
        assert q1 == q2
        rows = await client_module.get_client().execute(
            "SELECT COUNT(*), MIN(priority) FROM facebook_publish_queue "
            "WHERE publication_id = 'pub_idem' "
            "AND status IN ('queued', 'processing')"
        )
        assert rows.rows[0][0] == 1
        assert rows.rows[0][1] == 999

    asyncio.run(_go())


def test_stale_duplicate_failure_cannot_unschedule_success() -> None:
    """A late duplicate CLAIM_LOST must leave the winning publication/reel alone."""
    pipe_id, did = seed_connected("pl_stale", "ytd_stale")
    reel_db_id = seed_ready_reel("pl_stale", "r1")
    pub_id = "pub_stale"

    async def _stage():
        assert await reels.advance_status(reel_db_id, "new", "queued")
        await publications.get_or_create(
            publication_id=pub_id, reel_db_id=reel_db_id, destination_id=did
        )
        await publish_queue.enqueue_publish_job(
            pipeline_id=pipe_id, destination_id=did,
            reel_db_id=reel_db_id, publication_id=pub_id,
        )

    asyncio.run(_stage())

    qid = asyncio.run(
        client_module.get_client().execute(
            "SELECT id FROM facebook_publish_queue WHERE publication_id = :pub",
            {"pub": pub_id},
        )
    ).rows[0][0]
    queue_id = qid

    async def _win():
        await publications.mark_scheduled(pub_id, "vid_winner")
        await reels.mark_reel_scheduled(reel_db_id, "vid_winner")

    asyncio.run(_win())

    result = asyncio.run(_fail_job(
        queue_id, pub_id, Path("/tmp"), 0.0,
        "CLAIM_LOST", "Reel left queued state before processing.",
        reel_db_id=reel_db_id,
    ))
    assert result["superseded"] is True, result
    assert result["publication_failed"] is False, result

    async def _check():
        pub = await publications.get_publication(pub_id)
        assert pub is not None and pub["status"] == "scheduled"
        assert pub["youtube_video_id"] == "vid_winner"
        assert pub["last_error"] is None
        reel = await reels.get_reel(reel_db_id)
        assert reel is not None and reel["status"] == "scheduled"
        assert reel["retry_count"] == 0
        job = await publish_queue.get_job(queue_id)
        assert job is not None and job["status"] == "failed"
        assert job["error_code"] == "SUPERSEDED"

    asyncio.run(_check())


def test_shorts_ineligible_refills_same_slot_with_next_reel(monkeypatch) -> None:
    """A Shorts-ineligible file must not consume the slot: next AI-ready reel
    is enqueued for the exact same publishAt, with no YouTube call."""
    pipe_id, did = seed_connected("pl_refill", "ytd_refill")
    reel1 = seed_ready_reel("pl_refill", "r1")
    reel2 = seed_ready_reel("pl_refill", "r2")
    pub_id = "pub_refill"
    publish_at = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(microsecond=0)
    publish_at_iso = publish_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    local = publish_at.astimezone(tz)

    async def _stage():
        await schedules.upsert_schedule(
            pipe_id,
            enabled=True,
            timezone="Asia/Ho_Chi_Minh",
            max_daily_publish=5,
            batch_time="06:00",
            slots={local.weekday(): [local.strftime("%H:%M")]},
        )
        assert await reels.advance_status(reel1, "new", "queued")
        await publications.get_or_create(
            publication_id=pub_id, reel_db_id=reel1, destination_id=did
        )
        await publications.set_scheduled_publish_at(pub_id, publish_at_iso)
        await publications.set_upload_snapshot(pub_id, "shorts")
        await publish_queue.enqueue_publish_job(
            pipeline_id=pipe_id, destination_id=did,
            reel_db_id=reel1, publication_id=pub_id, priority=999,
        )

    asyncio.run(_stage())

    class FakeResolver:
        @classmethod
        def from_settings(cls, transport=None):
            return cls()

        async def resolve(self, url):
            return {"url": url}

        async def download_media(self, media, job_id, tmp_root=None):
            path = Path(tmp_root) / job_id / "video.mp4"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fake-video")
            return path

    monkeypatch.setattr(publisher_module, "FacebookMediaResolver", FakeResolver)
    import app.services.facebook_shorts as shorts_module
    monkeypatch.setattr(
        shorts_module,
        "check_shorts_eligibility",
        lambda _path: (False, "504s · 720x1280 vertical · vượt quá 180s"),
    )

    result = asyncio.run(run_publisher_once())
    assert result is not None and result["error_code"] == "SHORTS_INELIGIBLE", result
    assert result["publication_failed"] is True, result
    assert result["replacement"]["refilled"] is True, result

    async def _check():
        pub = await publications.get_publication(pub_id)
        assert pub is not None and pub["status"] == "failed"
        assert pub["shorts_eligible"] is False
        failed_reel = await reels.get_reel(reel1)
        assert failed_reel is not None and failed_reel["status"] == "skipped"
        next_reel = await reels.get_reel(reel2)
        assert next_reel is not None and next_reel["status"] == "queued"
        pubs = await publications.list_publications(did)
        replacement = next(p for p in pubs if p["status"] == "queued")
        assert replacement["scheduled_publish_at"] == publish_at_iso
        queued = await publish_queue.list_queued_jobs()
        assert len(queued) == 1, queued
        assert queued[0]["reel_db_id"] == reel2

    asyncio.run(_check())


def test_both_mode_uploads_ineligible_shorts_as_video(monkeypatch) -> None:
    """Both mode keeps the slot: ineligible Shorts are uploaded as normal videos."""
    pipe_id, did = seed_connected("pl_both", "ytd_both")
    reel1 = seed_ready_reel("pl_both", "r1")
    pub_id = "pub_both"
    publish_at = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(microsecond=0)
    publish_at_iso = publish_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    async def _stage():
        assert await reels.advance_status(reel1, "new", "queued")
        await publications.get_or_create(
            publication_id=pub_id, reel_db_id=reel1, destination_id=did
        )
        await publications.set_scheduled_publish_at(pub_id, publish_at_iso)
        await publications.set_upload_snapshot(pub_id, "both")
        await publish_queue.enqueue_publish_job(
            pipeline_id=pipe_id, destination_id=did,
            reel_db_id=reel1, publication_id=pub_id, priority=999,
        )

    asyncio.run(_stage())

    class FakeResolver:
        @classmethod
        def from_settings(cls, transport=None):
            return cls()

        async def resolve(self, url):
            return {"url": url}

        async def download_media(self, media, job_id, tmp_root=None):
            path = Path(tmp_root) / job_id / "video.mp4"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fake-video")
            return path

    async def _credentials(_destination_id):
        return {"token": "test-token"}

    async def _refresh(_destination_id, credentials):
        return credentials

    monkeypatch.setattr(publisher_module, "FacebookMediaResolver", FakeResolver)
    monkeypatch.setattr(publisher_module, "load_destination_credentials_async", _credentials)
    monkeypatch.setattr(publisher_module, "refresh_if_needed", _refresh)
    monkeypatch.setattr(publisher_module, "upload_video", lambda *args, **kwargs: "vid_both")
    import app.services.facebook_shorts as shorts_module
    monkeypatch.setattr(
        shorts_module,
        "check_shorts_eligibility",
        lambda _path: (False, "504s · 720x1280 vertical · vượt quá 180s"),
    )

    result = asyncio.run(run_publisher_once())
    assert result is not None and result["result"] == "scheduled", result
    assert result["youtube_video_id"] == "vid_both", result

    async def _check():
        pub = await publications.get_publication(pub_id)
        assert pub is not None and pub["status"] == "scheduled"
        assert pub["shorts_eligible"] is False
        assert "vượt quá 180s" in (pub["shorts_check_note"] or "")
        reel = await reels.get_reel(reel1)
        assert reel is not None and reel["status"] == "scheduled"
        assert await publish_queue.list_queued_jobs() == []

    asyncio.run(_check())
