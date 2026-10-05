import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

import app.db.client as client_module
import app.routes.publish as pub_module
from app.config import settings
from app.db.client import migrate
from app.db.repositories import destinations, pipelines, publications, reels, sources, youtube_auth
from app.main import create_app
from app.services.facebook_publish_worker import _PUBLISH_LOCK, run_publish_next
from app.services.facebook_youtube_publisher import (
    YouTubePublisherError,
    build_metadata,
    refresh_if_needed,
    upload_video,
    validate_visibility,
)

TEST_DB_PATH = Path("/tmp/backend_facebook_task7b_test.db")
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

CREDS_JSON = json.dumps({
    "token": "ya29.test",
    "refresh_token": "rt_test",
    "token_uri": "https://oauth2.googleapis.com/token",
    "client_id": "cid",
    "client_secret": "csecret",
    "scopes": [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
    ],
})


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
    settings.TOOLNET_BASE_URL = "https://toolnet.example.com/v1"
    settings.TOOLNET_API_KEY = "test_toolnet_key"
    settings.TOOLNET_MODEL = "groq/qwen/qwen3.8-27b"
    settings.TOOLNET_AI_ENABLED = True
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
        "tn_base": settings.TOOLNET_BASE_URL,
        "tn_key": settings.TOOLNET_API_KEY,
        "tn_model": settings.TOOLNET_MODEL,
        "tn_enabled": settings.TOOLNET_AI_ENABLED,
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
    settings.TOOLNET_BASE_URL = prev["tn_base"]
    settings.TOOLNET_API_KEY = prev["tn_key"]
    settings.TOOLNET_MODEL = prev["tn_model"]
    settings.TOOLNET_AI_ENABLED = prev["tn_enabled"]
    client_module._client = None


def seed(pid="pl_pub", did="ytd_pub", n=1, connected=True, enabled=True, visibility="public"):
    async def _go():
        await pipelines.create_pipeline(pipeline_id=pid, name="P", slug=pid)
        await sources.create_source(
            source_id=f"{pid}_src", pipeline_id=pid, page_id="111",
            reels_url="https://www.facebook.com/111/reels/",
        )
        await destinations.create_destination(
            destination_id=did, pipeline_id=pid, channel_id="UC_TEST" if connected else None,
            channel_name="Test Chan" if connected else None,
            visibility=visibility, enabled=enabled,
        )
        if connected:
            await destinations.set_connected(did, channel_id="UC_TEST", channel_name="Test Chan")
            await youtube_auth.save_credentials(did, CREDS_JSON)
        for i in range(n):
            await reels.insert_reel_if_new(
                reel_db_id=f"{pid}_r{i}", source_id=f"{pid}_src", reel_id=f"r{i}",
                reel_url=f"https://www.facebook.com/reel/{1000 + i}/",
                caption=f"cap {i}",
            )

    asyncio.run(_go())
    return pid, did


def mock_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


GOOD_AI_JSON = {
    "title": "AI Generated Title Number One",
    "description": "AI generated description.",
    "hashtags": ["#ai", "#test", "#reels"],
}


def ok_media_handler(request: httpx.Request) -> httpx.Response:
    if "chat/completions" in request.url.path:
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": json.dumps(GOOD_AI_JSON)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        })
    if request.url.path == "/fetch":
        return httpx.Response(200, json=MEDIA_JSON)
    return httpx.Response(200, content=b"V" * 4096, headers={"Content-Type": "video/mp4"})


class FakeCreds:
    expired = False
    refresh_token = "rt_test"
    token = "ya29.test"


class FakeInsertRequest:
    def __init__(self, behavior):
        self.behavior = behavior  # list of ("ok", id) | ("error", status, reason) | ("raise", exc)
        self.calls = 0

    def next_chunk(self):
        if self.calls >= len(self.behavior):
            return None, {"id": "yt_final"}
        action = self.behavior[self.calls]
        self.calls += 1
        if action[0] == "ok":
            return None, {"id": action[1]}
        if action[0] == "none":
            return None, None
        if action[0] == "raise":
            raise action[1]
        status, reason = action[1], action[2]
        from googleapiclient.errors import HttpError
        import httplib2

        resp = httplib2.Response({"status": status, "reason": reason})
        raise HttpError(resp, f'{{"error": {{"message": "{reason}"}}}}'.encode())


class FakeVideos:
    def __init__(self, request):
        self.request = request
        self.kwargs = None

    def insert(self, **kwargs):
        self.kwargs = kwargs
        return self.request


class FakeYouTube:
    def __init__(self, request):
        self._videos = FakeVideos(request)

    def videos(self):
        return self._videos


def reel_state(db_id: str) -> dict:
    async def _go():
        return await reels.get_reel(db_id)

    return asyncio.run(_go())


# ---------- validation ----------


def test_destination_missing(db) -> None:
    async def _go():
        await pipelines.create_pipeline(pipeline_id="pl_x", name="X", slug="pl_x")

    asyncio.run(_go())
    job = asyncio.run(run_publish_next("pl_x", "ytd_nope", tmp_root=db))
    assert job.result == "no_work" and job.error_code == "DESTINATION_NOT_FOUND"


def test_destination_disabled(db) -> None:
    pid, did = seed(pid="pl_dis", did="ytd_dis", enabled=False)
    job = asyncio.run(run_publish_next(pid, did, tmp_root=db))
    assert job.result == "failed" and job.error_code == "DESTINATION_DISABLED"
    assert reel_state(f"{pid}_r0")["status"] == "new"  # never claimed


def test_destination_disconnected(db) -> None:
    pid, did = seed(pid="pl_dc", did="ytd_dc", connected=False)
    job = asyncio.run(run_publish_next(pid, did, tmp_root=db))
    assert job.result == "failed" and job.error_code == "DESTINATION_NOT_CONNECTED"
    assert reel_state(f"{pid}_r0")["status"] == "new"


def test_credentials_missing_rejected(db) -> None:
    async def _go():
        await pipelines.create_pipeline(pipeline_id="pl_nc", name="N", slug="pl_nc")
        await destinations.create_destination(
            destination_id="ytd_nc", pipeline_id="pl_nc",
            channel_id="UC_X", channel_name="X",
        )
        await destinations.set_connected("ytd_nc", channel_id="UC_X", channel_name="X")

    asyncio.run(_go())
    # connected flag but no server-side credentials row
    job = asyncio.run(run_publish_next("pl_nc", "ytd_nc", tmp_root=db))
    assert job.result == "failed" and job.error_code == "DESTINATION_NOT_CONNECTED"


def test_wrong_pipeline_binding(db) -> None:
    pid, did = seed(pid="pl_a", did="ytd_a")
    seed(pid="pl_b", did="ytd_b", n=0)
    job = asyncio.run(run_publish_next("pl_b", did, tmp_root=db))
    assert job.result == "no_work" and job.error_code == "DESTINATION_NOT_FOUND"


def test_no_work_empty(db) -> None:
    pid, did = seed(n=0)
    job = asyncio.run(run_publish_next(pid, did, tmp_root=db))
    assert job.result == "no_work"


def test_invalid_visibility_rejected(db) -> None:
    with pytest.raises(YouTubePublisherError):
        validate_visibility("everyone")
    assert validate_visibility("Public") == "public"


def test_metadata_rules(db) -> None:
    title, desc = build_metadata(title="  cap  ", description=None, reel_id="r1", reel_url="https://u", visibility="public")
    assert title == "cap" and "https://u" in desc
    title, _ = build_metadata(title=None, description=None, reel_id="r9", reel_url=None, visibility="public")
    assert title == "Facebook Reel r9"
    title, _ = build_metadata(title="x" * 200, description="y" * 6000, reel_id="r", reel_url=None, visibility="public")
    assert len(title) == 100


# ---------- upload unit ----------


def _upload(tmp_path, behavior, visibility="public"):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"0" * 100)
    req = FakeInsertRequest(behavior)
    yt = FakeYouTube(req)
    vid = upload_video(
        FakeCreds(), f, "t", "d", visibility,
        youtube_factory=lambda creds: yt, sleep_fn=lambda s: None,
    )
    return vid, req


def test_upload_success_and_body(db, tmp_path) -> None:
    vid, req = _upload(tmp_path, [("none",), ("ok", "yt123")])
    assert vid == "yt123"
    assert req.calls == 2


def test_upload_5xx_retry(db, tmp_path) -> None:
    vid, req = _upload(tmp_path, [("error", 500, "boom"), ("error", 503, "boom"), ("ok", "yt9")])
    assert vid == "yt9" and req.calls == 3


def test_upload_403_quota_no_retry(db, tmp_path) -> None:
    with pytest.raises(YouTubePublisherError) as e:
        _upload(tmp_path, [("error", 403, "quotaExceeded: stop")])
    assert e.value.code == "YOUTUBE_QUOTA_EXCEEDED"


def test_upload_401_no_retry(db, tmp_path) -> None:
    with pytest.raises(YouTubePublisherError) as e:
        _upload(tmp_path, [("error", 401, "unauthorized")])
    assert e.value.code == "YOUTUBE_AUTH_FAILED"


def test_upload_no_video_id(db, tmp_path) -> None:
    with pytest.raises(YouTubePublisherError) as e:
        _upload(tmp_path, [("ok", "")])
    assert e.value.code == "YOUTUBE_UPLOAD_FAILED"


def test_upload_network_retry_then_give_up(db, tmp_path) -> None:
    with pytest.raises(YouTubePublisherError) as e:
        _upload(tmp_path, [("raise", ConnectionError("down"))] * 10)
    assert e.value.code == "YOUTUBE_NETWORK_ERROR"


# ---------- refresh ----------


def test_refresh_success_persists(db) -> None:
    pid, did = seed()
    creds = SimpleNamespace(expired=True, refresh_token="rt_test", token="old")

    def _refresh(request):
        creds.token = "ya29.new"

    creds.refresh = _refresh
    out = asyncio.run(refresh_if_needed(did, creds))
    assert out.token == "ya29.new"
    stored = json.loads(asyncio.run(youtube_auth.get_credentials(did)))
    assert stored["token"] == "ya29.new" and stored["refresh_token"] == "rt_test"


def test_refresh_missing_token_fails(db) -> None:
    pid, did = seed()
    creds = SimpleNamespace(expired=True, refresh_token=None, token="old")
    with pytest.raises(YouTubePublisherError) as e:
        asyncio.run(refresh_if_needed(did, creds))
    assert e.value.code == "YOUTUBE_AUTH_FAILED"


def test_refresh_failure_fails(db) -> None:
    pid, did = seed()

    def _boom(request):
        raise RuntimeError("nope")

    creds = SimpleNamespace(expired=True, refresh_token="rt_test", token="old", refresh=_boom)
    with pytest.raises(YouTubePublisherError) as e:
        asyncio.run(refresh_if_needed(did, creds))
    assert e.value.code == "YOUTUBE_AUTH_FAILED"


def test_creds_isolation(db) -> None:
    pid, did = seed()
    seed(pid="pl_iso2", did="ytd_iso2", n=0, connected=False)
    with pytest.raises(YouTubePublisherError) as e:
        asyncio.run(
            __import__("app.services.facebook_youtube_publisher", fromlist=["x"]).load_destination_credentials_async("ytd_iso2")
        )
    assert e.value.code == "YOUTUBE_AUTH_FAILED"


# ---------- worker ----------


def _run_publish(pid, did, tmp_path, factory, transport=None):
    return asyncio.run(
        run_publish_next(pid, did, tmp_root=tmp_path, transport=transport, youtube_factory=factory)
    )


def _factory_for(behaviors):
    state = {"i": 0, "services": []}

    def _factory(creds):
        req = FakeInsertRequest(behaviors[state["i"]])
        state["i"] += 1
        svc = FakeYouTube(req)
        state["services"].append(svc)
        return svc

    _factory.calls = state
    return _factory


def test_publish_success(db, tmp_path) -> None:
    pid, did = seed(n=1)
    t = mock_transport(ok_media_handler)
    factory = _factory_for([[("ok", "yt_success")]])
    job = _run_publish(pid, did, tmp_path, factory, transport=t)
    assert job.result == "published"
    assert job.youtube_video_id == "yt_success"
    assert job.file_bytes == 4096
    assert job.channel_id == "UC_TEST"
    assert job.ai_cached is False
    assert job.ai_model == "groq/qwen/qwen3.8-27b"
    assert job.title == GOOD_AI_JSON["title"]
    row = reel_state(f"{pid}_r0")
    assert row["status"] == "published" and row["youtube_video_id"] == "yt_success"

    async def _check_pub():
        return await publications.get_by_reel_destination(f"{pid}_r0", did)

    pub = asyncio.run(_check_pub())
    assert pub["status"] == "published" and pub["youtube_video_id"] == "yt_success"
    assert pub["youtube_title"] == GOOD_AI_JSON["title"]
    assert "#ai" in (pub["youtube_description"] or "")
    assert pub["ai_model"] == "groq/qwen/qwen3.8-27b"
    # generated title/description actually sent to YouTube
    sent = factory.calls["services"][0]._videos.kwargs
    assert sent["body"]["snippet"]["title"] == GOOD_AI_JSON["title"]
    assert "cap 0" not in sent["body"]["snippet"]["title"]
    assert len(sent["body"]["snippet"]["title"]) <= 100
    assert len(sent["body"]["snippet"]["description"]) <= 5000
    assert list(tmp_path.iterdir()) == []


def test_already_published_no_second_upload(db, tmp_path) -> None:
    pid, did = seed(n=1)
    t = mock_transport(ok_media_handler)
    j1 = _run_publish(pid, did, tmp_path, _factory_for([[("ok", "yt_1")]]), transport=t)
    assert j1.result == "published"
    # reel back to new would re-claim; simulate operator reset then retry
    asyncio.run(reels.update_reel_status(f"{pid}_r0", "new"))
    calls = {"n": 0}

    def _counting(creds):
        calls["n"] += 1
        return FakeYouTube(FakeInsertRequest([("ok", "yt_2")]))

    j2 = _run_publish(pid, did, tmp_path, _counting, transport=t)
    assert j2.result == "already_published"
    assert j2.youtube_video_id == "yt_1" and calls["n"] == 0


def test_resolve_fail_releases(db, tmp_path) -> None:
    pid, did = seed(n=1)

    def handler(req: httpx.Request) -> httpx.Response:
        if "chat/completions" in req.url.path:
            return httpx.Response(200, json={
                "choices": [{"message": {"content": json.dumps(GOOD_AI_JSON)}}],
                "usage": {},
            })
        return httpx.Response(500, text="boom")

    t = mock_transport(handler)
    job = _run_publish(pid, did, tmp_path, _factory_for([[("ok", "x")]]), transport=t)
    assert job.result == "failed" and "FASTSAVER" in (job.error_code or "")
    assert job.ai_cached is False  # AI succeeded before the download stage
    row = reel_state(f"{pid}_r0")
    assert row["status"] == "new" and row["retry_count"] == 1
    assert list(tmp_path.iterdir()) == []


def test_upload_fail_releases_and_cleans(db, tmp_path) -> None:
    pid, did = seed(n=1)
    t = mock_transport(ok_media_handler)
    job = _run_publish(
        pid, did, tmp_path,
        _factory_for([[("error", 403, "quotaExceeded")]]), transport=t,
    )
    assert job.result == "failed" and job.error_code == "YOUTUBE_QUOTA_EXCEEDED"
    row = reel_state(f"{pid}_r0")
    assert row["status"] == "new"

    async def _check_pub():
        return await publications.get_by_reel_destination(f"{pid}_r0", did)

    pub = asyncio.run(_check_pub())
    assert pub["status"] == "failed" and pub["retry_count"] == 1
    assert list(tmp_path.iterdir()) == []


def test_advance_conditional(db) -> None:
    pid, did = seed(n=1)

    async def _go():
        first = await reels.advance_status(f"{pid}_r0", "new", "queued")
        repeat = await reels.advance_status(f"{pid}_r0", "new", "queued")
        proc = await reels.advance_status(f"{pid}_r0", "queued", "processing")
        return first, repeat, proc

    first, repeat, proc = asyncio.run(_go())
    assert first is True and repeat is False and proc is True


def test_busy_lock(db, tmp_path) -> None:
    from app.services.facebook_publish_worker import _PUBLISH_LOCK

    pid, did = seed(n=1)

    async def _go():
        async with _PUBLISH_LOCK:
            return await run_publish_next(pid, did, tmp_root=tmp_path)

    job = asyncio.run(_go())
    assert job.result == "busy"


def test_endpoint_auth_shape_no_secrets(db, tmp_path, monkeypatch) -> None:
    import app.routes.publish as pub_module
    from app.services.facebook_publish_worker import PublishJobResult

    async def _stub(pid, did, **kw):
        return PublishJobResult(result="published", reel_id="r1", publication_id="p1",
                                youtube_video_id="yt1", channel_id="UC", file_bytes=10, elapsed_s=1.0)

    monkeypatch.setattr(pub_module, "run_publish_next", _stub)
    client = TestClient(create_app())
    pid, did = seed(n=1)
    r = client.post(f"/api/facebook/pipelines/{pid}/youtube-destinations/{did}/publish-next")
    assert r.status_code == 401
    r = client.post(
        f"/api/facebook/pipelines/{pid}/youtube-destinations/{did}/publish-next",
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["result"] == "published" and body["youtube_video_id"] == "yt1"
    blob = json.dumps(body)
    assert "ya29" not in blob and "rt_test" not in blob and "csecret" not in blob


def test_flow_state_publisher_mapping(db) -> None:
    from app.routes.flow import build_flow_state

    pid, did = seed(n=2)
    state = asyncio.run(build_flow_state(pid))
    assert state["steps"]["youtube_destination"] == "ready"
    assert state["steps"]["publisher"] == "idle"

    async def _make_failed():
        await publications.get_or_create(
            publication_id="pub_f", reel_db_id=f"{pid}_r0", destination_id=did
        )
        await publications.mark_failed("pub_f", "boom")

    asyncio.run(_make_failed())
    state = asyncio.run(build_flow_state(pid))
    assert state["steps"]["publisher"] == "error"


# ---------- Task 8B: AI-first publish ----------


def test_cached_ai_no_toolnet_call(db, tmp_path) -> None:
    from app.db.repositories import ai_metadata
    from app.db.repositories.ai_metadata import source_hash

    pid, did = seed(n=1)
    calls = {"n": 0}

    async def _seed_ai():
        await ai_metadata.upsert_generated(
            reel_db_id=f"{pid}_r0", title="Cached AI Title", description="Cached desc",
            hashtags=["#c", "#d", "#e"], model="groq/qwen/qwen3.8-27b",
            source_hash=source_hash("cap 0", "r0"),
        )

    asyncio.run(_seed_ai())

    def handler(req: httpx.Request) -> httpx.Response:
        if "chat/completions" in req.url.path:
            calls["n"] += 1
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "{}"}}], "usage": {}})
        return ok_media_handler(req)

    job = _run_publish(pid, did, tmp_path, _factory_for([[("ok", "yt_c")]]),
                       transport=mock_transport(handler))
    assert job.result == "published"
    assert job.ai_cached is True
    assert job.title == "Cached AI Title"
    assert calls["n"] == 0


def test_ai_fail_never_touches_media_or_youtube(db, tmp_path) -> None:
    pid, did = seed(n=1)
    seen = {"fetch": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if "chat/completions" in req.url.path:
            return httpx.Response(500, json={"error": "boom"})
        if req.url.path == "/fetch":
            seen["fetch"] += 1
        return httpx.Response(500, text="boom")

    factory_calls = {"n": 0}

    def _counting(creds):
        factory_calls["n"] += 1
        return FakeYouTube(FakeInsertRequest([("ok", "x")]))

    job = _run_publish(pid, did, tmp_path, _counting, transport=mock_transport(handler))
    assert job.result == "failed"
    assert job.error_code == "TOOLNET_UPSTREAM_ERROR"
    assert seen["fetch"] == 0
    assert factory_calls["n"] == 0
    row = reel_state(f"{pid}_r0")
    assert row["status"] == "new"  # released, never published

    async def _check_pub():
        return await publications.get_by_reel_destination(f"{pid}_r0", did)

    pub = asyncio.run(_check_pub())
    assert pub["status"] == "failed"
    assert list(tmp_path.iterdir()) == []


def test_ai_disabled_fails_before_download(db, tmp_path, monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "TOOLNET_AI_ENABLED", False)
    pid, did = seed(n=1)
    seen = {"fetch": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/fetch":
            seen["fetch"] += 1
        return ok_media_handler(req)

    job = _run_publish(pid, did, tmp_path, _factory_for([[("ok", "x")]]),
                       transport=mock_transport(handler))
    assert job.result == "failed"
    assert job.error_code == "TOOLNET_CONFIG_MISSING"
    assert seen["fetch"] == 0
    assert reel_state(f"{pid}_r0")["status"] == "new"


def test_stale_hash_regenerates_for_upload(db, tmp_path) -> None:
    from app.db.repositories import ai_metadata

    pid, did = seed(n=1)

    async def _seed_stale():
        await ai_metadata.upsert_generated(
            reel_db_id=f"{pid}_r0", title="Old", description="Old",
            hashtags=["#o", "#p", "#q"], model="other-model",
            source_hash="stale",
        )

    asyncio.run(_seed_stale())
    t = mock_transport(ok_media_handler)
    job = _run_publish(pid, did, tmp_path, _factory_for([[("ok", "yt_new")]]), transport=t)
    assert job.result == "published"
    assert job.ai_cached is False
    assert job.title == GOOD_AI_JSON["title"]


def test_hashtags_appended_once(db, tmp_path) -> None:
    from app.services.facebook_youtube_publisher import finalize_description

    out = finalize_description("Hello world #ai", ["#ai", "#test", "#reels"])
    assert out.count("#ai") == 1
    assert "#test" in out and "#reels" in out
    assert finalize_description(None, ["#a", "#b", "#c"]) == "#a #b #c"
    long_desc = "x" * 6000
    assert len(finalize_description(long_desc, ["#a", "#b", "#c"])) <= 5000


def test_skipped_never_claimed(db, tmp_path) -> None:
    pid, did = seed(n=1)
    asyncio.run(reels.update_reel_status(f"{pid}_r0", "skipped"))
    t = mock_transport(ok_media_handler)
    job = _run_publish(pid, did, tmp_path, _factory_for([[("ok", "x")]]), transport=t)
    assert job.result == "no_work"
    assert reel_state(f"{pid}_r0")["status"] == "skipped"


def test_snapshot_not_overwritten(db, tmp_path) -> None:
    pid, did = seed(n=1)
    t = mock_transport(ok_media_handler)
    job = _run_publish(pid, did, tmp_path, _factory_for([[("ok", "yt_snap")]]), transport=t)
    assert job.result == "published"

    async def _check():
        return await publications.get_by_reel_destination(f"{pid}_r0", did)

    pub = asyncio.run(_check())
    assert pub["youtube_title"] == GOOD_AI_JSON["title"]
    assert pub["ai_model"] == "groq/qwen/qwen3.8-27b"
    assert "yt_snap" in (pub["youtube_video_id"] or "")
