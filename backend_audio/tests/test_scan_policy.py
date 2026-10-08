"""Scan policy acceptance: scan-once, manual-only, scheduler never scans."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

ADMIN = {"X-Admin-Token": "test_admin_token"}


@pytest.fixture()
def client(db):
    return TestClient(create_app())


@pytest.fixture(autouse=True)
def _listing_env(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "AUDIO_RAPIDAPI_KEY", "test-key")
    monkeypatch.setattr(settings, "AUDIO_RAPIDAPI_HOST", "test-host")
    monkeypatch.setattr(settings, "AUDIO_RAPIDAPI_BASE_URL", "https://test-host")
    monkeypatch.setattr(settings, "AUDIO_FASTSAVER_BASE_URL", "")
    monkeypatch.setattr(settings, "AUDIO_FASTSAVER_API_KEY", "")


def _pipe(client, name="P"):
    return client.post("/api/audio/pipelines", headers=ADMIN,
                       json={"name": name}).json()["id"]


def _kill_auto_runs(source_id):
    from app.db.repositories import scan_runs

    run = scan_runs.active_run_for_source(source_id)
    if run is not None:
        scan_runs.update_run(run["id"], status="failed",
                             last_error_code="X", last_error_message="x")


def _source_id(client, pid):
    from app.db.client import get_client

    return dict(get_client().execute(
        "SELECT * FROM audio_sources WHERE pipeline_id = ?",
        (pid,)).fetchone())["id"]


def test_1_new_source_triggers_exactly_one_scan(db, client):
    import app.services.scanner as scanner

    pid = _pipe(client)
    calls = []
    orig = scanner.scan_source

    async def spy(source_id, **kw):
        calls.append(source_id)
        return await orig(source_id, **kw)

    scanner.scan_source = spy
    try:
        body = client.post(f"/api/audio/pipelines/{pid}/sources", headers=ADMIN,
                           json={"urls": "https://www.facebook.com/newpg/reels/"}).json()
    finally:
        scanner.scan_source = orig
    assert len(body["added"]) == 1
    assert calls == [body["added"][0]["id"]]
    _kill_auto_runs(body["added"][0]["id"])


def test_2_readd_existing_source_no_scan(db, client):
    import app.services.scanner as scanner

    pid = _pipe(client)
    url = "https://www.facebook.com/newpg/reels/"
    first = client.post(f"/api/audio/pipelines/{pid}/sources", headers=ADMIN,
                        json={"urls": url}).json()
    _kill_auto_runs(first["added"][0]["id"])
    calls = []
    orig = scanner.scan_source

    async def spy(source_id, **kw):
        calls.append(source_id)
        return await orig(source_id, **kw)

    scanner.scan_source = spy
    try:
        second = client.post(f"/api/audio/pipelines/{pid}/sources",
                             headers=ADMIN, json={"urls": url}).json()
    finally:
        scanner.scan_source = orig
    assert second["added"] == [] and len(second["existing"]) == 1
    assert calls == []


def test_3_scheduler_never_scans(db, client):
    import app.services.scheduler as sched

    from app.db.repositories import sources as src_repo

    pid = _pipe(client)
    src_repo.add_source(pid, "https://www.facebook.com/pg/reels/", "pg")
    for _ in range(100):
        out = sched.tick_pipeline(pid)
        assert out.get("reason") in ("scheduler disabled", "no connected destination",
                                     "queue empty", "waiting for next_run_at",
                                     "min gap not elapsed", "daily cap reached",
                                     "already queued", "queued")
    import app.services.scanner as scanner

    assert not hasattr(sched, "scan_source")
    import inspect

    src = inspect.getsource(sched)
    assert "scan_source" not in src and "import scanner" not in src


def test_4_restart_after_complete_no_rescan(db, client):
    import app.services.scanner as scanner
    from app.db.repositories import scan_runs

    pid = _pipe(client)
    client.post(f"/api/audio/pipelines/{pid}/sources", headers=ADMIN,
                json={"urls": "https://www.facebook.com/pg/reels/"})
    sid = _source_id(client, pid)
    _kill_auto_runs(sid)
    run = scan_runs.create_run(sid, pid, "initial")
    scan_runs.update_run(run["id"], status="completed",
                         pagination_exhausted=1, stop_reason="END_OF_RESULTS")
    assert scanner.recover_interrupted_scans() == 0
    assert scan_runs.active_run_for_source(sid) is None


def test_5_dashboard_reads_do_not_scan(db, client):
    pid = _pipe(client)
    client.post(f"/api/audio/pipelines/{pid}/sources", headers=ADMIN,
                json={"urls": "https://www.facebook.com/pg/reels/"})
    from app.db.repositories import scan_runs

    sid = _source_id(client, pid)
    _kill_auto_runs(sid)
    before = len(scan_runs.list_runs_for_source(sid))
    client.get(f"/api/audio/pipelines/{pid}/sources", headers=ADMIN)
    client.get(f"/api/audio/pipelines/{pid}/inventory", headers=ADMIN)
    client.get(f"/api/audio/pipelines/{pid}", headers=ADMIN)
    assert len(scan_runs.list_runs_for_source(sid)) == before


def test_6_7_scan_new_and_full_no_dupes(db, client):
    import asyncio

    import httpx
    import app.services.scanner as scanner
    from app.db.client import get_client
    from app.db.repositories import scan_runs

    pid = _pipe(client)
    client.post(f"/api/audio/pipelines/{pid}/sources", headers=ADMIN,
                json={"urls": "https://www.facebook.com/pg/reels/"})
    sid = _source_id(client, pid)
    _kill_auto_runs(sid)

    def pages(items_list):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/page/details"):
                return httpx.Response(200, json={"results": {"reels_page_id": "R"}})
            cursor = dict(request.url.params).get("cursor")
            idx = 0 if cursor is None else int(cursor)
            items, nxt = items_list[idx]
            return httpx.Response(200, json={"results": items, "cursor": nxt})

        return httpx.MockTransport(handler)

    def reel(i):
        return {"video_id": f"v{i}",
                "url": f"https://www.facebook.com/reel/v{i}/"}

    async def drive(mode_run_id, transport):
        await scanner._run_scan(mode_run_id, limit=5000, transport=transport)
        return scan_runs.get_run(mode_run_id)

    t1 = pages([([reel(1)], None)])
    r1 = scan_runs.create_run(sid, pid, "initial")
    r1 = asyncio.run(drive(r1["id"], t1))
    assert r1["videos_added"] == 1

    # Scan New with one extra video: only the new one is added.
    t2 = pages([([reel(1), reel(2)], None)])
    r2 = scan_runs.create_run(sid, pid, "incremental")
    r2 = asyncio.run(drive(r2["id"], t2))
    assert r2["videos_added"] == 1 and r2["videos_existing"] == 1

    # Full Scan over the same data: zero dupes.
    r3 = scan_runs.create_run(sid, pid, "full")
    r3 = asyncio.run(drive(r3["id"], t2))
    assert r3["videos_added"] == 0
    n = get_client().execute(
        "SELECT COUNT(*) AS n FROM audio_inventory WHERE pipeline_id = ?",
        (pid,)).fetchone()["n"]
    assert n == 2


def test_8_published_preserved(db, client):
    from app.db.client import get_client
    from app.db.repositories import sources as src_repo

    pid = _pipe(client)
    item, _ = src_repo.upsert_inventory_item(
        pid, None, "v9", "https://www.facebook.com/reel/v9/")
    get_client().execute("UPDATE audio_inventory SET status = 'published' "
                         "WHERE id = ?", (item["id"],))
    get_client().commit()
    item2, created = src_repo.upsert_inventory_item(
        pid, None, "v9", "https://www.facebook.com/reel/v9/")
    assert created is False and item2["status"] == "published"


def test_9_empty_queue_no_auto_scan(db, client):
    from app.services.scheduler import tick_pipeline

    pid = _pipe(client)
    out = tick_pipeline(pid)
    assert out["due"] is False  # scheduler disabled by default; never scans


def test_10_interrupted_initial_resumes_checkpoint(db, client):
    import asyncio

    import httpx
    import app.services.scanner as scanner
    from app.db.repositories import scan_runs

    pid = _pipe(client)
    client.post(f"/api/audio/pipelines/{pid}/sources", headers=ADMIN,
                json={"urls": "https://www.facebook.com/pg/reels/"})
    sid = _source_id(client, pid)
    _kill_auto_runs(sid)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/page/details"):
            return httpx.Response(200, json={"results": {"reels_page_id": "R"}})
        cursor = dict(request.url.params).get("cursor")
        if cursor is None:
            return httpx.Response(200, json={
                "results": [{"video_id": "v1",
                             "url": "https://www.facebook.com/reel/v1/"}],
                "cursor": "C1"})
        return httpx.Response(200, json={
            "results": [{"video_id": "v2",
                         "url": "https://www.facebook.com/reel/v2/"}],
            "cursor": None})

    transport = httpx.MockTransport(handler)
    run = scan_runs.create_run(sid, pid, "initial")
    scan_runs.update_run(run["id"], status="paused", next_cursor="C1",
                         pages_fetched=1, videos_discovered=1, videos_added=1)
    resumed = asyncio.run(scanner.scan_source(sid))
    assert resumed["run_id"] == run["id"]

    async def finish():
        scan_runs.update_run(run["id"], status="queued")
        await scanner._run_scan(run["id"], limit=5000, transport=transport)
        return scan_runs.get_run(run["id"])

    final = asyncio.run(finish())
    assert final["videos_added"] == 2 and final["videos_discovered"] == 2
