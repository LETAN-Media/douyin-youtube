import asyncio
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.db.client as client_module
from app.config import settings
from app.db.client import migrate
from app.db.repositories import pipelines, reels, scan_runs, sources
from app.main import create_app

TEST_DB_PATH = Path("/tmp/backend_facebook_flow_test.db")
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


def _make_pipeline(pid: str = "pl_flow", enabled: bool = True) -> dict:
    async def _go():
        return await pipelines.create_pipeline(
            pipeline_id=pid, name="Flow", slug=pid, enabled=enabled
        )

    return _run(_go())


def _make_source(sid: str = "src_flow", pid: str = "pl_flow") -> dict:
    async def _go():
        return await sources.create_source(
            source_id=sid,
            pipeline_id=pid,
            page_id="61592409539824",
            page_name=None,
            reels_url="https://www.facebook.com/61592409539824/reels/",
        )

    return _run(_go())


def _make_run(rid: str, sid: str, status: str = "queued") -> dict:
    async def _go():
        return await scan_runs.create_scan_run(
            scan_run_id=rid, source_id=sid, status=status
        )

    return _run(_go())


def _seed_reel(sid: str, reel_id: str, reel_status: str = "new") -> None:
    async def _go():
        await reels.insert_reel_if_new(
            reel_db_id=f"{sid}_{reel_id}", source_id=sid, reel_id=reel_id
        )
        if reel_status != "new":
            await reels.update_reel_status(f"{sid}_{reel_id}", reel_status)

    _run(_go())


def test_no_sources(db) -> None:
    _make_pipeline()
    prev_ai = settings.TOOLNET_AI_ENABLED
    settings.TOOLNET_AI_ENABLED = False
    try:
        body = TestClient(create_app()).get("/api/facebook/pipelines/pl_flow/flow-state").json()
    finally:
        settings.TOOLNET_AI_ENABLED = prev_ai
    assert body["live"] is True
    assert body["sources"] == 0 and body["inventory"] == 0
    assert body["steps"]["source"] == "idle"
    assert body["steps"]["inventory"] == "idle"
    assert body["steps"]["ai_metadata"] == "not_configured"
    assert body["queued"] == 0 and body["failed"] == 0


def test_scan_running(db) -> None:
    _make_pipeline()
    src = _make_source()
    _make_run("run1", src["id"], status="running")
    body = TestClient(create_app()).get("/api/facebook/pipelines/pl_flow/flow-state").json()
    assert body["steps"]["source"] == "ready"
    assert body["steps"]["inventory"] == "running"


def test_inventory_completed(db) -> None:
    _make_pipeline()
    src = _make_source()
    _seed_reel(src["id"], "111")
    _seed_reel(src["id"], "222", reel_status="queued")
    run = _make_run("run2", src["id"], status="queued")
    _run(scan_runs.complete_scan_run("run2", status="completed", crawl_complete=True))
    _run(
        sources.record_scan_finished(
            src["id"], status="completed", error=None,
            discovered_total=2, crawl_complete=True,
        )
    )
    assert run["id"] == "run2"
    body = TestClient(create_app()).get("/api/facebook/pipelines/pl_flow/flow-state").json()
    assert body["sources"] == 1 and body["inventory"] == 2
    assert body["queued"] == 1 and body["processing"] == 0
    assert body["steps"]["source"] == "ready"
    assert body["steps"]["inventory"] == "ready"


def test_scan_failed_no_inventory(db) -> None:
    _make_pipeline()
    src = _make_source()
    _make_run("run3", src["id"], status="queued")
    _run(
        scan_runs.complete_scan_run(
            "run3", status="failed", error="boom", stop_reason="RAPIDAPI_TIMEOUT"
        )
    )
    _run(
        sources.record_scan_finished(
            src["id"], status="failed", error="boom",
            discovered_total=0, crawl_complete=False,
        )
    )
    body = TestClient(create_app()).get("/api/facebook/pipelines/pl_flow/flow-state").json()
    assert body["steps"]["inventory"] == "error"
    assert body["steps"]["source"] == "error"


def test_failed_scan_with_inventory_stays_done(db) -> None:
    _make_pipeline()
    src = _make_source()
    _seed_reel(src["id"], "111")
    _make_run("run4", src["id"], status="queued")
    _run(scan_runs.complete_scan_run("run4", status="failed", error="boom"))
    _run(
        sources.record_scan_finished(
            src["id"], status="failed", error="boom",
            discovered_total=1, crawl_complete=False,
        )
    )
    body = TestClient(create_app()).get("/api/facebook/pipelines/pl_flow/flow-state").json()
    assert body["inventory"] == 1
    assert body["steps"]["inventory"] == "ready"


def test_unknown_pipeline_404(db) -> None:
    r = TestClient(create_app()).get("/api/facebook/pipelines/nope/flow-state")
    assert r.status_code == 404
    assert r.json()["error"] == "PIPELINE_NOT_FOUND"


# ---------- publisher step: historical failures are not errors ----------


def _make_destination(did: str = "ytd_flow", pid: str = "pl_flow") -> dict:
    from app.db.repositories import destinations

    async def _go():
        return await destinations.create_destination(
            destination_id=did, pipeline_id=pid, channel_id="UC_X",
            channel_name="X",
        )

    return _run(_go())


def _failed_publication(pub_id: str, reel_db_id: str, did: str) -> None:
    from app.db.repositories import publications

    async def _go():
        await publications.get_or_create(
            publication_id=pub_id, reel_db_id=reel_db_id, destination_id=did
        )
        await publications.mark_failed(pub_id, "SLOT_MISSED: old failure")

    _run(_go())


def _flow_publisher(db) -> tuple[str, str]:
    client = TestClient(create_app())
    r = client.get("/api/facebook/pipelines/pl_flow/flow-state")
    assert r.status_code == 200, r.text
    body = r.json()
    return body["steps"]["publisher"], body["details"]["publisher"]


def test_publisher_failed_history_is_ready_not_error(db) -> None:
    _make_pipeline()
    _make_source()
    _make_destination()
    _seed_reel("src_flow", "r1", "new")
    _failed_publication("pub_old", "src_flow_r1", "ytd_flow")

    status, detail = _flow_publisher(db)
    assert status == "ready", (status, detail)
    assert "failed history" in detail


def test_publisher_failed_with_live_queue_is_error(db) -> None:
    from app.db.repositories import publish_queue

    _make_pipeline()
    _make_source()
    _make_destination()
    _seed_reel("src_flow", "r1", "new")
    _failed_publication("pub_old", "src_flow_r1", "ytd_flow")
    _seed_reel("src_flow", "r2", "queued")

    async def _enqueue():
        await publish_queue.enqueue_publish_job(
            pipeline_id="pl_flow", destination_id="ytd_flow",
            reel_db_id="src_flow_r2", publication_id="pub_live",
        )

    _run(_enqueue())
    status, detail = _flow_publisher(db)
    assert status == "error", (status, detail)
    assert "failed" in detail


def test_publisher_processing_is_running(db) -> None:
    from app.db.repositories import publications

    _make_pipeline()
    _make_source()
    _make_destination()
    _seed_reel("src_flow", "r1", "processing")

    async def _mk():
        await publications.get_or_create(
            publication_id="pub_run", reel_db_id="src_flow_r1",
            destination_id="ytd_flow",
        )
        client = __import__("app.db.client", fromlist=["get_client"]).get_client()
        await client.execute(
            "UPDATE publications SET status = 'processing' WHERE id = 'pub_run'"
        )

    _run(_mk())
    status, detail = _flow_publisher(db)
    assert status == "running", (status, detail)
