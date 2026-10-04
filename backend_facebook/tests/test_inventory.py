import asyncio
import os
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app.db.client as client_module
import app.routes.scan as scan_module
from app.config import settings
from app.db.client import get_client, migrate
from app.db.repositories import pipelines, reels, scan_runs, sources
from app.main import create_app
from app.routes.scan import run_initial_scan

TEST_DB_PATH = Path("/tmp/backend_facebook_task5_test.db")
TEST_DB_URL = f"file:{TEST_DB_PATH}"
ADMIN = "test_admin_token"
AUTH_HEADERS = {"X-Admin-Token": ADMIN}
PAGE_ID = "61592409539824"
RPID = "RPID_TEST_123"


def fresh_db() -> None:
    client_module._client = None
    os.environ["ADMIN_TOKEN"] = ADMIN
    os.environ["TURSO_DATABASE_URL"] = TEST_DB_URL
    os.environ["TURSO_AUTH_TOKEN"] = "test_token"
    settings.ADMIN_TOKEN = ADMIN
    settings.TURSO_DATABASE_URL = TEST_DB_URL
    settings.TURSO_AUTH_TOKEN = "test_token"
    settings.RAPIDAPI_KEY = "test_key_1"
    settings.RAPIDAPI_KEY_FALLBACK = None
    settings.FACEBOOK_RAPIDAPI_HOST = "test-host"
    settings.FACEBOOK_RAPIDAPI_BASE_URL = "https://test-host"
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    for suffix in ("-wal", "-shm", "-journal"):
        p = Path(str(TEST_DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    asyncio.run(migrate())


@pytest.fixture()
def db():
    prev = {
        "url": os.environ.get("TURSO_DATABASE_URL"),
        "token": os.environ.get("TURSO_AUTH_TOKEN"),
        "admin": os.environ.get("ADMIN_TOKEN"),
        "settings_url": settings.TURSO_DATABASE_URL,
        "key": settings.RAPIDAPI_KEY,
        "fallback": settings.RAPIDAPI_KEY_FALLBACK,
        "host": settings.FACEBOOK_RAPIDAPI_HOST,
        "base": settings.FACEBOOK_RAPIDAPI_BASE_URL,
        "stop": settings.FACEBOOK_INCREMENTAL_KNOWN_PAGES_STOP,
    }
    fresh_db()
    yield
    client_module._client = None
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    if prev["url"] is not None:
        os.environ["TURSO_DATABASE_URL"] = prev["url"]
    if prev["token"] is not None:
        os.environ["TURSO_AUTH_TOKEN"] = prev["token"]
    if prev["admin"] is not None:
        os.environ["ADMIN_TOKEN"] = prev["admin"]
    settings.TURSO_DATABASE_URL = prev["settings_url"]
    settings.RAPIDAPI_KEY = prev["key"]
    settings.RAPIDAPI_KEY_FALLBACK = prev["fallback"]
    settings.FACEBOOK_RAPIDAPI_HOST = prev["host"]
    settings.FACEBOOK_RAPIDAPI_BASE_URL = prev["base"]
    settings.FACEBOOK_INCREMENTAL_KNOWN_PAGES_STOP = prev["stop"]
    client_module._client = None


@pytest.fixture()
def no_sleep(monkeypatch):
    async def _fast(_s: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _fast)


def make_pipeline(suffix: str) -> dict:
    async def _run() -> dict:
        try:
            return await pipelines.create_pipeline(
                pipeline_id=f"p{suffix}", name=f"P{suffix}", slug=f"p{suffix}"
            )
        except Exception:
            return await pipelines.get_pipeline(f"p{suffix}")

    return asyncio.run(_run())


def make_source(suffix: str, completed: bool = False) -> dict:
    async def _run() -> dict:
        try:
            await pipelines.create_pipeline(
                pipeline_id=f"p{suffix}", name=f"P{suffix}", slug=f"p{suffix}"
            )
        except Exception:
            pass
        try:
            src = await sources.create_source(
                source_id=f"src{suffix}",
                pipeline_id=f"p{suffix}",
                page_id=PAGE_ID,
                page_name=None,
                reels_url=f"https://www.facebook.com/{PAGE_ID}/reels/",
            )
        except Exception:
            src = await sources.get_source(f"src{suffix}")
        if completed:
            await sources.record_scan_finished(
                f"src{suffix}", status="completed", error=None,
                discovered_total=0, crawl_complete=True,
            )
            src = await sources.get_source(f"src{suffix}")
        return src

    return asyncio.run(_run())


def seed_reel(source_id: str, reel_id: str, status: str = "new") -> None:
    async def _run() -> None:
        await reels.insert_reel_if_new(
            reel_db_id=f"{source_id}_{reel_id}", source_id=source_id, reel_id=reel_id
        )
        if status != "new":
            await reels.update_reel_status(f"{source_id}_{reel_id}", status)

    asyncio.run(_run())


def make_run(source_id: str, run_id: str) -> dict:
    async def _run() -> dict:
        return await scan_runs.create_scan_run(
            scan_run_id=run_id, source_id=source_id, status="queued"
        )

    return asyncio.run(_run())


def reel_item(vid: str) -> dict:
    return {
        "type": "reel",
        "video_id": vid,
        "post_id": f"post_{vid}",
        "url": f"https://www.facebook.com/reel/{vid}/",
        "description": f"caption {vid}",
        "timestamp": 1791039716,
    }


def provider_transport(pages: dict, *, calls: list | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        path = request.url.path
        if path == "/page/details":
            return httpx.Response(200, json={"results": {"reels_page_id": RPID}})
        if path == "/page/reels":
            cursor = request.url.params.get("cursor")
            key = cursor  # None for first page
            if key in pages:
                code, body = pages[key]
                return httpx.Response(code, json=body)
            return httpx.Response(404, json={"detail": "no mock"})
        return httpx.Response(404, json={"detail": "unknown"})

    return httpx.MockTransport(handler)


# ---------- 1. incremental 0 new ----------


def test_incremental_zero_new(db, no_sleep) -> None:
    src = make_source("a", completed=True)
    seed_reel(src["id"], "111")
    seed_reel(src["id"], "222")
    make_run(src["id"], "inc1")
    calls: list = []
    t = provider_transport(
        {
            None: (200, {"results": [reel_item("111")], "cursor": "C2"}),
            "C2": (200, {"results": [reel_item("222")], "cursor": "C3"}),
            "C3": (200, {"results": [reel_item("111")], "cursor": None}),
        },
        calls=calls,
    )
    asyncio.run(run_initial_scan("inc1", transport=t, mode="incremental"))
    run = asyncio.run(scan_runs.get_scan_run("inc1"))
    assert run["scan_mode"] == "incremental"
    assert run["inserted_count"] == 0
    assert run["existing_count"] > 0
    assert run["stop_reason"] == "KNOWN_REELS_REACHED"
    assert run["crawl_complete"] is True
    assert run["status"] == "completed"
    stored = asyncio.run(sources.get_source(src["id"]))
    assert stored["discovered_total"] == 2


# ---------- 2. incremental with new ----------


def test_incremental_with_new(db, no_sleep) -> None:
    src = make_source("b", completed=True)
    seed_reel(src["id"], "111")
    make_run(src["id"], "inc2")
    t = provider_transport(
        {
            None: (200, {"results": [reel_item("999"), reel_item("111")], "cursor": "C2"}),
            "C2": (200, {"results": [reel_item("111")], "cursor": "C3"}),
            "C3": (200, {"results": [reel_item("111")], "cursor": None}),
        }
    )
    asyncio.run(run_initial_scan("inc2", transport=t, mode="incremental"))
    run = asyncio.run(scan_runs.get_scan_run("inc2"))
    assert run["inserted_count"] == 1
    assert run["stop_reason"] == "KNOWN_REELS_REACHED"
    assert asyncio.run(sources.get_source(src["id"]))["discovered_total"] == 2


# ---------- 3. two known pages -> stop, bounded requests ----------


def test_two_known_pages_stop(db, no_sleep) -> None:
    src = make_source("c", completed=True)
    seed_reel(src["id"], "111")
    make_run(src["id"], "inc3")
    calls: list = []
    t = provider_transport(
        {
            None: (200, {"results": [reel_item("111")], "cursor": "C2"}),
            "C2": (200, {"results": [reel_item("111")], "cursor": "C3"}),
            "C3": (200, {"results": [reel_item("111")], "cursor": None}),
        },
        calls=calls,
    )
    asyncio.run(run_initial_scan("inc3", transport=t, mode="incremental"))
    reel_calls = [u for u in calls if "/page/reels" in u]
    assert len(reel_calls) == 2  # stopped after exactly 2 known pages
    run = asyncio.run(scan_runs.get_scan_run("inc3"))
    assert run["stop_reason"] == "KNOWN_REELS_REACHED"


# ---------- 4. one known page then new -> no early stop ----------


def test_no_early_stop_after_single_known(db, no_sleep) -> None:
    src = make_source("d", completed=True)
    seed_reel(src["id"], "111")
    make_run(src["id"], "inc4")
    calls: list = []
    t = provider_transport(
        {
            None: (200, {"results": [reel_item("111")], "cursor": "C2"}),
            "C2": (200, {"results": [reel_item("222")], "cursor": "C3"}),
            "C3": (200, {"results": [reel_item("111")], "cursor": "C4"}),
            "C4": (200, {"results": [reel_item("111")], "cursor": None}),
        },
        calls=calls,
    )
    asyncio.run(run_initial_scan("inc4", transport=t, mode="incremental"))
    run = asyncio.run(scan_runs.get_scan_run("inc4"))
    assert run["inserted_count"] == 1
    reel_calls = [u for u in calls if "/page/reels" in u]
    assert len(reel_calls) == 4


# ---------- 5/6/7. duplicate + status safety ----------


def test_status_safety(db, no_sleep) -> None:
    src = make_source("e", completed=True)
    seed_reel(src["id"], "pub1", status="published")
    seed_reel(src["id"], "q1", status="queued")
    seed_reel(src["id"], "proc1", status="processing")
    seed_reel(src["id"], "f1", status="failed")
    make_run(src["id"], "inc5")
    t = provider_transport(
        {None: (200, {"results": [reel_item("pub1"), reel_item("q1"), reel_item("proc1"), reel_item("f1")], "cursor": None})}
    )
    asyncio.run(run_initial_scan("inc5", transport=t, mode="incremental"))
    run = asyncio.run(scan_runs.get_scan_run("inc5"))
    assert run["inserted_count"] == 0 and run["existing_count"] == 4
    for rid, want in (("pub1", "published"), ("q1", "queued"), ("proc1", "processing"), ("f1", "failed")):
        row = asyncio.run(reels.get_reel(f"{src['id']}_{rid}"))
        assert row["status"] == want, rid
    assert asyncio.run(sources.get_source(src["id"]))["discovered_total"] == 4


# ---------- 8. discovered_total ----------


def test_discovered_total_is_count(db, no_sleep) -> None:
    src = make_source("f", completed=True)
    seed_reel(src["id"], "111")
    make_run(src["id"], "inc6")
    t = provider_transport(
        {None: (200, {"results": [reel_item("111"), reel_item("222")], "cursor": None})}
    )
    asyncio.run(run_initial_scan("inc6", transport=t, mode="incremental"))
    assert asyncio.run(sources.get_source(src["id"]))["discovered_total"] == 2


# ---------- 9. inventory pagination ----------


def test_inventory_pagination(db) -> None:
    pipe = make_pipeline("g")
    src = make_source("g")
    for i in range(5):
        seed_reel(src["id"], f"90{i}")
    client = TestClient(create_app())
    r = client.get(f"/api/facebook/pipelines/{pipe['id']}/inventory?limit=2&offset=0")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 5 and len(body["items"]) == 2
    assert body["next_cursor"] == "2"
    assert body["unpublished"] == 5 and body["published"] == 0
    r2 = client.get(f"/api/facebook/pipelines/{pipe['id']}/inventory?limit=2&offset=4")
    b2 = r2.json()
    assert len(b2["items"]) == 1 and b2["next_cursor"] is None
    item = b2["items"][0]
    for key in ("id", "source_id", "reel_id", "reel_url", "status", "discovered_at"):
        assert key in item, key
    rf = client.get(f"/api/facebook/pipelines/{pipe['id']}/inventory?status=new&limit=50")
    assert rf.json()["total"] == 5


# ---------- 10. stats ----------


def test_inventory_stats(db) -> None:
    pipe = make_pipeline("h")
    src = make_source("h")
    seed_reel(src["id"], "n1", status="new")
    seed_reel(src["id"], "n2", status="new")
    seed_reel(src["id"], "q1", status="queued")
    seed_reel(src["id"], "p1", status="published")
    seed_reel(src["id"], "f1", status="failed")
    stats = asyncio.run(reels.inventory_stats(pipe["id"]))
    assert stats == {
        "total": 5, "new": 2, "queued": 1, "processing": 0,
        "published": 1, "failed": 1, "skipped": 0, "unpublished": 4,
    }
    client = TestClient(create_app())
    r = client.get(f"/api/facebook/pipelines/{pipe['id']}/inventory/stats")
    assert r.status_code == 200 and r.json()["total"] == 5


# ---------- 11/12. selection priority + fallback ----------


def test_select_newest_and_fallback(db) -> None:
    async def _seed() -> None:
        try:
            await pipelines.create_pipeline(pipeline_id="pi", name="Pi", slug="pi")
        except Exception:
            pass
        await sources.create_source(
            source_id="srci", pipeline_id="pi", page_id=PAGE_ID, page_name=None
        )
        for rid, pub in (("old1", "2024-01-01T00:00:00+00:00"), ("new1", "2026-09-01T00:00:00+00:00")):
            await reels.insert_reel_if_new(
                reel_db_id=f"srci_{rid}", source_id="srci", reel_id=rid,
                source_published_at=pub,
            )

    asyncio.run(_seed())
    top = asyncio.run(reels.select_next_unpublished_reel("pi"))
    assert top is not None and top["reel_id"] == "new1"

    async def _only_old() -> None:
        try:
            await pipelines.create_pipeline(pipeline_id="pj", name="Pj", slug="pj")
        except Exception:
            pass
        await sources.create_source(
            source_id="srcj", pipeline_id="pj", page_id=PAGE_ID, page_name=None
        )
        await reels.insert_reel_if_new(
            reel_db_id="srcj_old9", source_id="srcj", reel_id="old9"
        )

    asyncio.run(_only_old())
    top = asyncio.run(reels.select_next_unpublished_reel("pj"))
    assert top is not None and top["reel_id"] == "old9"


# ---------- 13/14. atomic claim ----------


def test_claim_and_contention(db) -> None:
    pipe = make_pipeline("k")
    src = make_source("k")
    seed_reel(src["id"], "c1")
    seed_reel(src["id"], "c2")
    client = TestClient(create_app())
    r1 = client.post(
        f"/api/facebook/pipelines/{pipe['id']}/inventory/claim-next", headers=AUTH_HEADERS
    )
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert b1["claimed"] is True
    r2 = client.post(
        f"/api/facebook/pipelines/{pipe['id']}/inventory/claim-next", headers=AUTH_HEADERS
    )
    b2 = r2.json()
    assert b2["claimed"] is True and b2["reel"]["id"] != b1["reel"]["id"]
    # direct double-claim on the same row: conditional update affects 0 rows
    res = asyncio.run(
        get_client().execute(
            "UPDATE facebook_reels SET status='queued' WHERE id=:id AND status='new'",
            {"id": b1["reel"]["id"]},
        )
    )
    assert (res.rows_affected or 0) == 0
    r3 = client.post(
        f"/api/facebook/pipelines/{pipe['id']}/inventory/claim-next"
    )
    assert r3.status_code == 401


# ---------- 15. empty ----------


def test_claim_empty(db) -> None:
    pipe = make_pipeline("l")
    make_source("l")
    client = TestClient(create_app())
    r = client.post(
        f"/api/facebook/pipelines/{pipe['id']}/inventory/claim-next", headers=AUTH_HEADERS
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {"reel": None, "claimed": False, "reason": "INVENTORY_EMPTY"}


# ---------- 16/17. release ----------


def test_release(db) -> None:
    pipe = make_pipeline("m")
    src = make_source("m")
    seed_reel(src["id"], "r1", status="queued")
    seed_reel(src["id"], "r2", status="published")
    assert asyncio.run(reels.release_claim(f"{src['id']}_r1")) is True
    assert (asyncio.run(reels.get_reel(f"{src['id']}_r1")))["status"] == "new"
    assert asyncio.run(reels.release_claim(f"{src['id']}_r2")) is False
    client = TestClient(create_app())
    # r1 already back to new -> endpoint must reject
    r = client.post(f"/api/facebook/reels/{src['id']}_r1/release", headers=AUTH_HEADERS)
    assert r.status_code == 409
    r = client.post(f"/api/facebook/reels/r2/release", headers=AUTH_HEADERS)
    assert r.status_code == 409  # published cannot release
    # release via bare reel_id works when uniquely matching and queued
    seed_reel(src["id"], "r3", status="queued")
    r = client.post("/api/facebook/reels/r3/release", headers=AUTH_HEADERS)
    assert r.status_code == 200 and r.json()["released"] is True


# ---------- 18. stale recovery ----------


def test_stale_queued_recovery(db) -> None:
    pipe = make_pipeline("n")
    src = make_source("n")
    seed_reel(src["id"], "s1", status="queued")
    seed_reel(src["id"], "s2", status="queued")
    seed_reel(src["id"], "s3", status="processing")
    seed_reel(src["id"], "s4", status="published")
    asyncio.run(
        get_client().execute(
            "UPDATE facebook_reels SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now','-3 hours') WHERE id = :id",
            {"id": f"{src['id']}_s1"},
        )
    )
    n = asyncio.run(reels.recover_stale_queued(max_age_minutes=120))
    assert n == 1
    assert (asyncio.run(reels.get_reel(f"{src['id']}_s1")))["status"] == "new"
    assert (asyncio.run(reels.get_reel(f"{src['id']}_s2")))["status"] == "queued"
    assert (asyncio.run(reels.get_reel(f"{src['id']}_s3")))["status"] == "processing"
    assert (asyncio.run(reels.get_reel(f"{src['id']}_s4")))["status"] == "published"


# ---------- mode params + auto ----------


def test_scan_mode_auto_and_explicit(db, monkeypatch, no_sleep) -> None:
    fresh_src = make_source("o", completed=False)
    done_src = make_source("p", completed=True)
    seen: list = []

    async def _noop(scan_run_id: str, transport=None, mode: str = "auto") -> None:
        seen.append((scan_run_id, mode))

    monkeypatch.setattr(scan_module, "run_initial_scan", _noop)
    client = TestClient(create_app())
    r = client.post(f"/api/facebook/sources/{fresh_src['id']}/scan", headers=AUTH_HEADERS)
    assert r.status_code == 202
    r = client.post(f"/api/facebook/sources/{done_src['id']}/scan", headers=AUTH_HEADERS)
    assert r.status_code == 202
    r = client.post(f"/api/facebook/sources/{done_src['id']}/scan?mode=full", headers=AUTH_HEADERS)
    assert r.status_code == 409  # already queued from previous line
    r = client.post(f"/api/facebook/sources/{fresh_src['id']}/scan?mode=bogus", headers=AUTH_HEADERS)
    assert r.status_code == 400
    runs = asyncio.run(scan_runs.list_scan_runs(done_src["id"]))
    assert runs and runs[0]["scan_mode"] == "incremental"
    runs = asyncio.run(scan_runs.list_scan_runs(fresh_src["id"]))
    assert runs and runs[0]["scan_mode"] == "initial"


def test_explicit_full_on_completed_source(db, no_sleep) -> None:
    src = make_source("q", completed=True)
    seed_reel(src["id"], "111")
    make_run(src["id"], "full1")
    t = provider_transport(
        {None: (200, {"results": [reel_item("111"), reel_item("222")], "cursor": None})}
    )
    asyncio.run(run_initial_scan("full1", transport=t, mode="full"))
    run = asyncio.run(scan_runs.get_scan_run("full1"))
    assert run["scan_mode"] == "initial"
    assert run["inserted_count"] == 1
    assert run["stop_reason"] == "END_OF_RESULTS"


def test_health(db) -> None:
    client = TestClient(create_app())
    r = client.get("/health")
    assert r.status_code == 200


def test_ready_db_ok(db) -> None:
    client = TestClient(create_app())
    r = client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["db"] == "ok" and body["ok"] is True


def test_ready_no_secret_leak(db) -> None:
    import app.routes.health as health_module

    settings.RAPIDAPI_KEY = "SECRETKEY123"
    try:
        out = health_module._redact("connect SECRETKEY123 failed at tail SECRETKEY123")
        assert "SECRETKEY123" not in out
    finally:
        settings.RAPIDAPI_KEY = "test_key_1"
