"""P1.1: FastSaver independence, redirect SSRF, pause/resume/restart recovery."""

import asyncio

import httpx
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
    # Isolate from real local .env credentials; individual tests opt in.
    monkeypatch.setattr(settings, "AUDIO_FASTSAVER_BASE_URL", "")
    monkeypatch.setattr(settings, "AUDIO_FASTSAVER_API_KEY", "")


def _phimtat_menu():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "title": "Update shortcuts at snapvideo.co",
            "medias": {"Close": "{{open-url}}"}})

    return httpx.MockTransport(handler)


def _fastsaver_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/fetch")
        return httpx.Response(200, json={
            "ok": True, "download_url": "https://cdn.example/v.mp4",
            "type": "video", "source": "facebook"})

    return httpx.MockTransport(handler)


def _no_phimtat(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "PHIMTAT_ENABLED", False)
    monkeypatch.setattr(settings, "PHIMTAT_API_KEY", "")


def _with_fastsaver(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "AUDIO_FASTSAVER_BASE_URL",
                        "https://fastsaver.example")
    monkeypatch.setattr(settings, "AUDIO_FASTSAVER_API_KEY", "fs-key")


def test_phimtat_disabled_fastsaver_only(db, monkeypatch):
    import asyncio

    from app.services import snapvideo as sv

    _no_phimtat(monkeypatch)
    _with_fastsaver(monkeypatch)
    out = asyncio.run(sv.resolve_media_url(
        "https://www.facebook.com/reel/123/",
        transport=_phimtat_menu(), fastsaver_transport=_fastsaver_ok()))
    assert out["provider"] == "fastsaver"
    assert out["media_url"] == "https://cdn.example/v.mp4"


def test_phimtat_failure_falls_back_to_fastsaver(db, monkeypatch):
    import asyncio

    from app.services import snapvideo as sv

    _with_fastsaver(monkeypatch)
    out = asyncio.run(sv.resolve_media_url(
        "https://www.facebook.com/reel/123/",
        transport=_phimtat_menu(), fastsaver_transport=_fastsaver_ok()))
    assert out["provider"] == "fastsaver"


def test_no_resolver_configured_fails_loud(db, monkeypatch):
    import asyncio

    from app.services import snapvideo as sv

    _no_phimtat(monkeypatch)
    with pytest.raises(sv.SnapVideoError) as exc:
        asyncio.run(sv.resolve_media_url("https://www.facebook.com/reel/123/"))
    assert exc.value.code == "SNAPVIDEO_NOT_CONFIGURED"


def test_download_works_without_phimtat_key(db, tmp_path, monkeypatch):
    import asyncio

    from app.services import snapvideo as sv

    _no_phimtat(monkeypatch)
    _with_fastsaver(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "video/mp4"},
                              content=b"data" * 50)

    dest = tmp_path / "v.mp4"
    out = asyncio.run(sv.stream_download(
        "https://cdn.example/v.mp4", dest, skip_ssrf_check=True,
        transport=httpx.MockTransport(handler)))
    assert out.stat().st_size == 200


def test_redirect_to_private_ip_blocked(db, tmp_path):
    import asyncio

    from app.services import snapvideo as sv

    def handler(request: httpx.Request) -> httpx.Response:
        if "cdn.example" in str(request.url):
            return httpx.Response(
                302, headers={"location": "http://127.0.0.1/evil.mp4"})
        return httpx.Response(200, headers={"content-type": "video/mp4"},
                              content=b"evil")

    async def main():
        with pytest.raises(sv.SnapVideoError):
            await sv.stream_download(
                "https://cdn.example/v.mp4", tmp_path / "e.mp4",
                transport=httpx.MockTransport(handler))
        assert not (tmp_path / "e.mp4").exists()

    asyncio.run(main())


def test_download_timeout_cleans_partial(db, tmp_path):
    import asyncio

    from app.services import snapvideo as sv

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    async def main():
        with pytest.raises(sv.SnapVideoError):
            await sv.stream_download(
                "https://cdn.example/v.mp4", tmp_path / "p.mp4",
                skip_ssrf_check=True,
                transport=httpx.MockTransport(handler))
        assert not (tmp_path / "p.mp4").exists()

    asyncio.run(main())


def _make_source(client):
    pid = client.post("/api/audio/pipelines", headers=ADMIN,
                      json={"name": "P"}).json()["id"]
    body = client.post(f"/api/audio/pipelines/{pid}/sources", headers=ADMIN,
                       json={"urls": "https://www.facebook.com/pg/reels/"}).json()
    return pid, body["added"][0]["id"]


def test_pause_resume_reuses_run(db, client):
    import app.services.scanner as scanner
    from app.db.repositories import scan_runs

    pid, sid = _make_source(client)
    # Kill the auto-queued placeholder so the test controls state.
    auto = scan_runs.active_run_for_source(sid)
    scan_runs.update_run(auto["id"], status="failed",
                         last_error_code="X", last_error_message="x")
    run = scan_runs.create_run(sid, pid, "initial")
    scan_runs.update_run(run["id"], status="paused", next_cursor="CURSOR1")
    resumed = asyncio.run(scanner.scan_source(sid))
    assert resumed["run_id"] == run["id"]
    # A fresh explicit full scan creates a new run (after the old one ends).
    scan_runs.update_run(run["id"], status="failed",
                         last_error_code="X", last_error_message="x")
    full = asyncio.run(scanner.scan_source(sid, full=True))
    assert full["run_id"] != run["id"]
    for rid in (run["id"], full["run_id"]):
        scan_runs.update_run(rid, status="failed",
                             last_error_code="X", last_error_message="x")


def test_restart_recovery_marks_paused_and_resumes(db, client):
    import app.services.scanner as scanner
    from app.db.client import get_client
    from app.db.repositories import scan_runs

    pid, sid = _make_source(client)
    auto = scan_runs.active_run_for_source(sid)
    scan_runs.update_run(auto["id"], status="running", next_cursor="CURSOR9")
    assert scanner.recover_interrupted_scans() == 1
    mid = scan_runs.get_run(auto["id"])
    assert mid["status"] == "paused"
    assert mid["next_cursor"] == "CURSOR9"
    resumed = asyncio.run(scanner.scan_source(sid))
    assert resumed["run_id"] == auto["id"]
    scan_runs.update_run(auto["id"], status="failed",
                         last_error_code="X", last_error_message="x")
