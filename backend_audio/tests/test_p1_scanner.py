"""P1: scanner pagination/checkpoint/resume + PHIMTAT contract + downloads."""

import asyncio
import json

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
    # Isolate resolver tests from real local .env credentials.
    monkeypatch.setattr(settings, "AUDIO_FASTSAVER_BASE_URL", "")
    monkeypatch.setattr(settings, "AUDIO_FASTSAVER_API_KEY", "")


def _pipe(client, name="P"):
    return client.post("/api/audio/pipelines", headers=ADMIN,
                       json={"name": name}).json()["id"]


def _add_source(client, pid, url="https://www.facebook.com/somepage/reels/"):
    body = client.post(f"/api/audio/pipelines/{pid}/sources", headers=ADMIN,
                       json={"urls": url}).json()
    assert len(body["added"]) == 1, body
    return body["added"][0]


# ---- P1-01 multi-source input ----

def test_add_four_sources_one_request(db, client):
    pid = _pipe(client)
    urls = "\n".join([
        "https://www.facebook.com/pageA/reels/",
        "https://www.facebook.com/pageB/reels/",
        "https://www.facebook.com/people/Example/123456789/",
        "https://www.facebook.com/987654321/?sk=reels_tab",
    ])
    body = client.post(f"/api/audio/pipelines/{pid}/sources", headers=ADMIN,
                       json={"urls": urls}).json()
    assert len(body["added"]) == 4
    assert body["existing"] == [] and body["invalid"] == []


def test_duplicate_and_invalid_sources(db, client):
    pid = _pipe(client)
    url = "https://www.facebook.com/pageA/reels/"
    first = client.post(f"/api/audio/pipelines/{pid}/sources", headers=ADMIN,
                        json={"urls": url}).json()
    assert len(first["added"]) == 1
    second = client.post(
        f"/api/audio/pipelines/{pid}/sources", headers=ADMIN,
        json={"urls": f"{url}\nhttps://www.facebook.com/pageA/reels/?q=1\nnotaurl"}).json()
    assert second["added"] == []
    assert len(second["existing"]) == 2
    assert len(second["invalid"]) == 1


# ---- scan helpers (mocked provider) ----

def _listing_pages(pages):
    """MockTransport serving /page/details + /page/reels cursor pages."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        path = request.url.path
        if path.endswith("/page/details"):
            return httpx.Response(200, json={
                "results": {"reels_page_id": "RP123"}})
        assert path.endswith("/page/reels")
        params = dict(request.url.params)
        cursor = params.get("cursor")
        idx = 0 if cursor is None else int(cursor)
        items, nxt = pages[idx]
        return httpx.Response(200, json={
            "results": items, "cursor": nxt})

    return httpx.MockTransport(handler), calls


def _reel(i, **kw):
    d = {"video_id": f"v{i}", "url": f"https://www.facebook.com/reel/v{i}/",
         "description": f"cap {i}"}
    d.update(kw)
    return d


def _run_scan(source_id, transport, limit=5000):
    import app.services.scanner as scanner

    async def main():
        # Bypass the auto-queued placeholder run; drive _run_scan directly.
        from app.db.repositories import scan_runs

        run = scan_runs.create_run(source_id, "pid-x", "initial")
        await scanner._run_scan(run["id"], limit=limit, transport=transport)
        return scan_runs.get_run(run["id"])

    return asyncio.run(main())


def _source_row(db, client, pid):
    from app.db.client import get_client

    return dict(get_client().execute(
        "SELECT * FROM audio_sources WHERE pipeline_id = ?",
        (pid,)).fetchone())


# ---- P1-02/03/04 pagination, checkpoint, resume ----

def test_initial_scan_paginates_and_persists(db, client):
    pid = _pipe(client)
    _add_source(client, pid)
    src = _source_row(db, client, pid)
    transport, calls = _listing_pages([
        ([_reel(1), _reel(2)], "1"),
        ([_reel(3)], None),
    ])
    run = _run_scan(src["id"], transport)
    assert run["status"] == "completed"
    assert run["videos_discovered"] == 3 and run["videos_added"] == 3
    assert run["pagination_exhausted"] == 1
    assert run["stop_reason"] == "END_OF_RESULTS"
    from app.db.client import get_client

    n = get_client().execute(
        "SELECT COUNT(*) AS n FROM audio_inventory WHERE pipeline_id = ?",
        (pid,)).fetchone()["n"]
    assert n == 3
    assert calls["n"] == 3  # details + 2 pages


def test_incremental_scan_stops_at_known(db, client):
    import app.services.scanner as scanner
    from app.db.repositories import scan_runs

    pid = _pipe(client)
    _add_source(client, pid)
    src = _source_row(db, client, pid)
    transport, _ = _listing_pages([([_reel(1)], None)])
    _run_scan(src["id"], transport)
    # Second run is incremental: 3 consecutive all-known pages stop it.
    transport2, _ = _listing_pages([
        ([_reel(1)], "1"),
        ([_reel(1)], "2"),
        ([_reel(1)], "3"),
        ([_reel(1)], None),
    ])
    run2 = scan_runs.create_run(src["id"], pid, "incremental")

    async def main():
        await scanner._run_scan(run2["id"], limit=5000, transport=transport2)
        return scan_runs.get_run(run2["id"])

    run2 = asyncio.run(main())
    assert run2["stop_reason"] == "KNOWN_ITEMS_REACHED"
    assert run2["videos_added"] == 0 and run2["videos_existing"] == 1
    from app.db.client import get_client

    n = get_client().execute(
        "SELECT COUNT(*) AS n FROM audio_inventory WHERE pipeline_id = ?",
        (pid,)).fetchone()["n"]
    assert n == 1


def test_same_video_across_pages_counted_once(db, client):
    pid = _pipe(client)
    _add_source(client, pid)
    src = _source_row(db, client, pid)
    transport, _ = _listing_pages([
        ([_reel(1), _reel(2)], "1"),
        ([_reel(2), _reel(3)], None),  # v2 repeated
    ])
    run = _run_scan(src["id"], transport)
    assert run["videos_discovered"] == 3 and run["videos_added"] == 3


def test_interrupted_scan_resumes_from_cursor(db, client):
    import app.services.scanner as scanner
    from app.db.repositories import scan_runs

    pid = _pipe(client)
    _add_source(client, pid)
    src = _source_row(db, client, pid)
    transport, _ = _listing_pages([
        ([_reel(1)], "1"),
        ([_reel(2)], None),
    ])
    run = scan_runs.create_run(src["id"], pid, "full")

    async def main():
        # Simulate a pause right after the first page persists.
        import app.db.repositories.scan_runs as scan_runs_mod

        orig = scan_runs_mod.get_run
        seen = {"n": 0}

        def spying(run_id):
            r = orig(run_id)
            if r and r["status"] == "running" and (r["videos_discovered"] or 0) >= 1:
                scan_runs.update_run(run_id, status="paused")
            return r

        scan_runs_mod.get_run = spying
        try:
            await scanner._run_scan(run["id"], limit=5000, transport=transport)
        finally:
            scan_runs_mod.get_run = orig
        mid = scan_runs.get_run(run["id"])
        assert mid["status"] == "paused"
        assert mid["next_cursor"] == "1"
        # Resume: requeue as running and continue to the end.
        scan_runs.update_run(run["id"], status="running")
        await scanner._run_scan(run["id"], limit=5000, transport=transport)
        return scan_runs.get_run(run["id"])

    final = asyncio.run(main())
    assert final["status"] == "completed"
    assert final["videos_added"] == 2


def test_concurrent_duplicate_scan_returns_same_run(db, client):
    import app.services.scanner as scanner

    pid = _pipe(client)
    _add_source(client, pid)  # route auto-starts the initial scan (queued)
    from app.db.client import get_client
    from app.db.repositories import scan_runs

    src = dict(get_client().execute(
        "SELECT * FROM audio_sources WHERE pipeline_id = ?",
        (pid,)).fetchone())
    auto = scan_runs.active_run_for_source(src["id"])
    assert auto is not None
    second = asyncio.run(scanner.scan_source(src["id"]))
    assert second["run_id"] == auto["id"]
    scan_runs.update_run(auto["id"], status="failed",
                         last_error_code="X", last_error_message="x")


def test_published_inventory_preserved_on_rescan(db, client):
    from app.db.client import get_client

    pid = _pipe(client)
    _add_source(client, pid)
    src = _source_row(db, client, pid)
    transport, _ = _listing_pages([([_reel(1)], None)])
    _run_scan(src["id"], transport)
    get_client().execute(
        "UPDATE audio_inventory SET status = 'published' WHERE pipeline_id = ?",
        (pid,))
    get_client().commit()
    _run_scan(src["id"], transport)
    row = get_client().execute(
        "SELECT status FROM audio_inventory WHERE pipeline_id = ?",
        (pid,)).fetchone()
    assert row["status"] == "published"


# ---- P1-05 provider errors ----

def _error_transport(status, body=""):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/page/details"):
            return httpx.Response(200, json={"results": {"reels_page_id": "R"}})
        return httpx.Response(status, text=body)

    return httpx.MockTransport(handler)


def test_provider_rate_limit_and_timeout_fail_loud(db, client):
    pid = _pipe(client)
    _add_source(client, pid)
    src = _source_row(db, client, pid)
    run = _run_scan(src["id"], _error_transport(429, "rate limited"))
    assert run["status"] == "failed" and run["last_error_code"] == "LISTING_RATE_LIMITED"
    assert run["videos_added"] == 0


def test_provider_missing_credentials(db, client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "AUDIO_RAPIDAPI_KEY", "")
    monkeypatch.setattr(settings, "AUDIO_RAPIDAPI_BASE_URL", "https://x")
    monkeypatch.setattr(settings, "AUDIO_RAPIDAPI_HOST", "x")
    pid = _pipe(client)
    _add_source(client, pid)
    src = _source_row(db, client, pid)
    run = _run_scan(src["id"], _error_transport(200))
    assert run["status"] == "failed"
    assert run["last_error_code"] == "LISTING_NOT_CONFIGURED"


# ---- P1-06/07 resolver + download ----

def _phimtat_transport(medias, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "red64.php" in request.url.path
        return httpx.Response(status, json={
            "title": "T", "thumbnail": "https://img/t.jpg",
            "medias": medias, "source": "snapvideo.co"})

    return httpx.MockTransport(handler)


def test_phimtat_normalizes_mp4_hd(db):
    import asyncio

    from app.services import snapvideo as sv

    transport = _phimtat_transport({
        "MP4 HD": "https://cdn.example/v_hd.mp4",
        "MP4 SD": "https://cdn.example/v_sd.mp4"})
    out = asyncio.run(sv.resolve_media_url(
        "https://www.facebook.com/reel/123/", transport=transport))
    assert out["media_url"] == "https://cdn.example/v_hd.mp4"
    assert out["provider"] == "phimtat"


def test_phimtat_menu_fallback_is_unresolvable(db):
    import asyncio

    from app.services import snapvideo as sv

    transport = _phimtat_transport({
        "JPG UPDATE GUIDE": "https://img/x.jpg",
        "Close": "{{open-url}}"})
    with pytest.raises(sv.SnapVideoError) as exc:
        asyncio.run(sv.resolve_media_url(
            "https://www.facebook.com/reel/123/", transport=transport))
    assert exc.value.code == "SNAPVIDEO_UNRESOLVABLE"


def test_resolver_rejects_non_facebook(db):
    import asyncio

    from app.services import snapvideo as sv

    with pytest.raises(sv.SnapVideoError):
        asyncio.run(sv.resolve_media_url("https://example.com/x.mp4"))


def test_streamed_download_paths(db, tmp_path):
    import asyncio

    from app.services import snapvideo as sv

    body = b"0123456789" * 100

    def ok_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "video/mp4"},
                              content=body)

    def html_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"},
                              content=b"<html></html>")

    async def main():
        dest = tmp_path / "v.mp4"
        out = await sv.stream_download(
            "https://cdn.example/v.mp4", dest, skip_ssrf_check=True,
            transport=httpx.MockTransport(ok_handler))
        assert out.stat().st_size == len(body)
        with pytest.raises(sv.SnapVideoError):
            await sv.stream_download(
                "https://cdn.example/x.mp4", tmp_path / "h.mp4",
                skip_ssrf_check=True,
                transport=httpx.MockTransport(html_handler))
        assert not (tmp_path / "h.mp4").exists()
        with pytest.raises(sv.SnapVideoError):
            await sv.stream_download(
                "https://cdn.example/big.mp4", tmp_path / "b.mp4",
                max_bytes=10, skip_ssrf_check=True,
                transport=httpx.MockTransport(ok_handler))
        assert not (tmp_path / "b.mp4").exists()

    asyncio.run(main())


def test_ssrf_guard_rejects_private_hosts(db):
    from app.services import snapvideo as sv

    with pytest.raises(sv.SnapVideoError):
        sv._assert_public_http_url("http://127.0.0.1/video.mp4")
    with pytest.raises(sv.SnapVideoError):
        sv._assert_public_http_url("file:///etc/passwd")


def test_phimtat_consent_gate_flow(db):
    import asyncio

    from app.services import snapvideo as sv

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if "agree-terms.php" in request.url.path:
            return httpx.Response(200, json={"ok": True, "agreed": True})
        if calls["n"] == 1:
            return httpx.Response(200, json={
                "title": "terms", "medias": {
                    "agree": "https://api.snapvideo.co/agree-terms.php?x=1",
                    "Close": "{{open-link}}"}})
        return httpx.Response(200, json={
            "title": "Real Title", "thumbnail": "https://img/t.jpg",
            "medias": {"MP4 HD": "https://cdn.example/hd.mp4",
                       "MP4 SD": "https://cdn.example/sd.mp4"}})

    out = asyncio.run(sv.resolve_media_url(
        "https://www.facebook.com/reel/123/",
        transport=httpx.MockTransport(handler)))
    assert out["media_url"] == "https://cdn.example/hd.mp4"
    assert out["provider"] == "phimtat"
    assert calls["n"] == 3
