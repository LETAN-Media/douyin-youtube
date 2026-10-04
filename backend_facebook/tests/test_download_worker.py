import asyncio
import os
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app.db.client as client_module
import app.routes.inventory as inv_module
from app.config import settings
from app.db.client import migrate
from app.db.repositories import pipelines, reels, sources
from app.main import create_app
from app.services.facebook_download_worker import _JOB_LOCK, run_download_next

TEST_DB_PATH = Path("/tmp/backend_facebook_task6c_test.db")
TEST_DB_URL = f"file:{TEST_DB_PATH}"
ADMIN = "test_admin_token"
AUTH_HEADERS = {"X-Admin-Token": ADMIN}

MEDIA_JSON = {
    "ok": True,
    "id": "abc",
    "source": "facebook.com",
    "type": "video",
    "download_url": "https://cdn.example.com/v.mp4?sig=1",
    "thumbnail_url": "https://cdn.example.com/t.jpg",
    "duration": 34,
    "caption": "hello",
}


def fresh_db() -> None:
    client_module._client = None
    os.environ["ADMIN_TOKEN"] = ADMIN
    os.environ["TURSO_DATABASE_URL"] = TEST_DB_URL
    os.environ["TURSO_AUTH_TOKEN"] = "test_token"
    settings.ADMIN_TOKEN = ADMIN
    settings.TURSO_DATABASE_URL = TEST_DB_URL
    settings.TURSO_AUTH_TOKEN = "test_token"
    settings.FASTSAVER_API_KEY = "test_fs_key"
    settings.FASTSAVER_BASE_URL = "https://api.example.com"
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    for suffix in ("-wal", "-shm", "-journal"):
        p = Path(str(TEST_DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    asyncio.run(migrate())


@pytest.fixture()
def db(tmp_path):
    prev = {
        "url": os.environ.get("TURSO_DATABASE_URL"),
        "admin": os.environ.get("ADMIN_TOKEN"),
        "settings_url": settings.TURSO_DATABASE_URL,
        "fs_key": settings.FASTSAVER_API_KEY,
        "fs_base": settings.FASTSAVER_BASE_URL,
    }
    fresh_db()
    yield tmp_path
    client_module._client = None
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    if prev["url"] is not None:
        os.environ["TURSO_DATABASE_URL"] = prev["url"]
    if prev["admin"] is not None:
        os.environ["ADMIN_TOKEN"] = prev["admin"]
    settings.TURSO_DATABASE_URL = prev["settings_url"]
    settings.FASTSAVER_API_KEY = prev["fs_key"]
    settings.FASTSAVER_BASE_URL = prev["fs_base"]
    client_module._client = None


def seed_pipeline_with_reels(n: int = 1, pid: str = "pl_w") -> str:
    async def _go():
        await pipelines.create_pipeline(pipeline_id=pid, name="W", slug=pid)
        await sources.create_source(
            source_id=f"{pid}_src", pipeline_id=pid, page_id="111",
            reels_url="https://www.facebook.com/111/reels/",
        )
        for i in range(n):
            await reels.insert_reel_if_new(
                reel_db_id=f"{pid}_r{i}", source_id=f"{pid}_src", reel_id=f"r{i}",
                reel_url=f"https://www.facebook.com/reel/{1000 + i}/",
            )

    asyncio.run(_go())
    return pid


def mock_transport(handler, calls: list | None = None) -> httpx.MockTransport:
    def _h(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        return handler(request)

    return httpx.MockTransport(_h)


def ok_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/fetch":
        return httpx.Response(200, json=MEDIA_JSON)
    return httpx.Response(200, content=b"V" * 2048, headers={"Content-Type": "video/mp4"})


def reel_state(db_id: str) -> dict:
    async def _go():
        return await reels.get_reel(db_id)

    return asyncio.run(_go())


def test_no_work_empty_pipeline(db) -> None:
    async def _go():
        await pipelines.create_pipeline(pipeline_id="pl_empty", name="E", slug="pl_empty")

    asyncio.run(_go())
    job = asyncio.run(run_download_next("pl_empty", tmp_root=db))
    assert job.result == "no_work"


def test_success_claim_download_release(db) -> None:
    pid = seed_pipeline_with_reels(1)
    job = asyncio.run(
        run_download_next(pid, tmp_root=db, transport=mock_transport(ok_handler))
    )
    assert job.result == "downloaded"
    assert job.file_bytes == 2048
    assert job.reel_id == "r0"
    row = reel_state(f"{pid}_r0")
    assert row["status"] == "new"  # handed back, never published
    assert row["retry_count"] == 0
    assert list(db.iterdir()) == []  # temp cleaned


def test_sequential_claims_differ(db) -> None:
    pid = seed_pipeline_with_reels(2)
    t = mock_transport(ok_handler)
    j1 = asyncio.run(run_download_next(pid, tmp_root=db, transport=t))
    assert j1.result == "downloaded"
    # simulate the future publish step consuming r0, then worker must take r1
    asyncio.run(reels.update_reel_status(f"{pid}_{j1.reel_id}", "published"))
    j2 = asyncio.run(run_download_next(pid, tmp_root=db, transport=t))
    assert j2.result == "downloaded"
    assert j2.reel_id != j1.reel_id
    # published reels are never re-claimed
    assert reel_state(f"{pid}_{j1.reel_id}")["status"] == "published"


def test_resolver_error_releases_claim(db) -> None:
    pid = seed_pipeline_with_reels(1)
    t = mock_transport(lambda req: httpx.Response(500, text="boom"))
    job = asyncio.run(run_download_next(pid, tmp_root=db, transport=t))
    assert job.result == "failed"
    assert job.error_code == "FASTSAVER_UPSTREAM_ERROR"
    row = reel_state(f"{pid}_r0")
    assert row["status"] == "new"
    assert row["retry_count"] == 1
    assert "FASTSAVER_UPSTREAM_ERROR" in (row["last_error"] or "")
    assert list(db.iterdir()) == []


def test_download_error_releases_claim(db) -> None:
    def _h(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/fetch":
            return httpx.Response(200, json=MEDIA_JSON)
        return httpx.Response(200, content=b"<html>", headers={"Content-Type": "text/html"})

    pid = seed_pipeline_with_reels(1)
    job = asyncio.run(run_download_next(pid, tmp_root=db, transport=mock_transport(_h)))
    assert job.result == "failed"
    assert job.error_code == "MEDIA_BAD_CONTENT_TYPE"
    row = reel_state(f"{pid}_r0")
    assert row["status"] == "new"
    assert row["retry_count"] == 1
    assert list(db.iterdir()) == []  # partial cleaned


def test_busy_when_locked(db) -> None:
    pid = seed_pipeline_with_reels(1)

    async def _go():
        async with _JOB_LOCK:
            return await run_download_next(pid, tmp_root=db)

    job = asyncio.run(_go())
    assert job.result == "busy"
    assert reel_state(f"{pid}_r0")["status"] == "new"  # untouched


def test_stale_queued_not_blindly_reclaimed(db) -> None:
    pid = seed_pipeline_with_reels(1)
    asyncio.run(reels.claim_next_reel(pid))  # simulate a stuck claim from a dead worker
    job = asyncio.run(run_download_next(pid, tmp_root=db, transport=mock_transport(ok_handler)))
    assert job.result == "no_work"  # stuck queued is not reclaimed blindly
    assert reel_state(f"{pid}_r0")["status"] == "queued"
    n = asyncio.run(reels.recover_stale_queued(max_age_minutes=10**9))
    assert n == 0  # fresh claim is NOT stale


async def _recover_old(pid: str) -> int:
    # backdate the stuck claim, then recover
    from app.db.client import get_client

    client = get_client()
    await client.execute(
        "UPDATE facebook_reels SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now','-3 hours') "
        "WHERE id = :id",
        {"id": f"{pid}_r0"},
    )
    return await reels.recover_stale_queued(max_age_minutes=60)


def test_recovered_claim_downloads(db) -> None:
    pid = seed_pipeline_with_reels(1)
    asyncio.run(reels.claim_next_reel(pid))
    assert asyncio.run(_recover_old(pid)) == 1
    job = asyncio.run(run_download_next(pid, tmp_root=db, transport=mock_transport(ok_handler)))
    assert job.result == "downloaded"
    assert reel_state(f"{pid}_r0")["status"] == "new"


def test_endpoint_auth_and_shape(db, monkeypatch) -> None:
    from app.services.facebook_download_worker import DownloadJobResult

    async def _stub(pid: str, **kw):
        return DownloadJobResult(result="downloaded", reel_id="r9", file_bytes=123, elapsed_s=1.2)

    monkeypatch.setattr(inv_module, "run_download_next", _stub)
    client = TestClient(create_app())
    r = client.post("/api/facebook/pipelines/pl_x/download-next")
    assert r.status_code == 401
    pid = seed_pipeline_with_reels(1, pid="pl_ep")
    r = client.post(f"/api/facebook/pipelines/{pid}/download-next", headers=AUTH_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body == {"ok": True, "result": "downloaded", "reel_id": "r9", "bytes": 123, "elapsed_s": 1.2}
    assert "download_url" not in body and "api_key" not in str(body).lower()


def test_endpoint_no_work_shape(db, monkeypatch) -> None:
    from app.services.facebook_download_worker import DownloadJobResult

    async def _stub(pid: str, **kw):
        return DownloadJobResult(result="no_work")

    monkeypatch.setattr(inv_module, "run_download_next", _stub)
    client = TestClient(create_app())

    async def _mk():
        await pipelines.create_pipeline(pipeline_id="pl_ep2b", name="E", slug="pl_ep2b")

    asyncio.run(_mk())
    r = client.post("/api/facebook/pipelines/pl_ep2b/download-next", headers=AUTH_HEADERS)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "result": "no_work"}
