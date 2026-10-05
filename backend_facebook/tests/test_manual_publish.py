"""Manual Facebook -> YouTube publishing (no inventory, no scheduler).

No real YouTube/FastSaver: httpx.MockTransport serves FastSaver resolve +
media bytes and ToolNet completions; a fake youtube_factory stands in for
upload. Covers: channel listing (safe fields), resolve without leaking the
signed download URL, AI metadata via the owning pipeline's settings, mocked
immediate + scheduled publish, duplicate protection + force, credential
isolation, /tmp cleanup, manual-before-auto claim order, failed jobs never
sticking the shared loop.
"""

import asyncio
import json
import os
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app.db.client as client_module
from app.config import settings
from app.db.client import migrate
from app.db.repositories import destinations, pipelines, sources, youtube_auth
from app.db.repositories import manual_publications as manual_repo
from app.db.repositories import publish_queue
from app.main import create_app
from app.services.facebook_manual_publisher import (
    generate_manual_metadata,
    process_manual_job,
)

TEST_DB_PATH = Path("/tmp/backend_facebook_manual_test.db")
TEST_DB_URL = f"file:{TEST_DB_PATH}"
ADMIN = "test_admin_token"
AUTH_HEADERS = {"X-Admin-Token": ADMIN}

VIDEO_URL = "https://www.facebook.com/reel/123456789/"
FETCH_JSON = {
    "ok": True,
    "download_url": "https://cdn.example.com/video.mp4",
    "type": "video",
    "source": "facebook",
    "duration": 12.5,
    "thumbnail_url": "https://cdn.example.com/thumb.jpg",
    "caption": "Caption gốc từ Facebook",
}

GOOD_AI = {
    "title": "Tiêu đề AI cho video thủ công",
    "description": "Mô tả AI.",
    "hashtags": ["#thcong", "#vlog", "#reels"],
}


def _completion(content: str) -> dict:
    return {
        "id": "chatcmpl-x",
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
    }


def fastsaver_transport() -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/fetch":
            return httpx.Response(200, json=FETCH_JSON)
        if "cdn.example.com/video.mp4" in str(req.url):
            return httpx.Response(
                200, content=b"0" * 1024, headers={"Content-Type": "video/mp4"}
            )
        return httpx.Response(404, json={"ok": False})

    return httpx.MockTransport(handler)


def toolnet_transport() -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion(json.dumps(GOOD_AI)))

    return httpx.MockTransport(handler)


class _FakeVideos:
    def __init__(self, req):
        self._req = req

    def insert(self, *args, **kwargs):
        return self._req


class _FakeInsertRequest:
    def __init__(self, video_id="yt_manual_123"):
        self._video_id = video_id
        self.calls = 0

    def next_chunk(self):
        self.calls += 1
        return None, {"id": self._video_id}


class _FakeYouTube:
    def __init__(self, req):
        self._videos = _FakeVideos(req)

    def videos(self):
        return self._videos


def fake_youtube_factory(*args, **kwargs):
    return _FakeYouTube(_FakeInsertRequest())


CREDS = json.dumps({
    "token": "ya29.test", "refresh_token": "rt", "token_uri": "https://oauth2.googleapis.com/token",
    "client_id": "cid", "client_secret": "csec",
    "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
})

_KEYS = (
    "ADMIN_TOKEN", "TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN",
    "TOOLNET_BASE_URL", "TOOLNET_API_KEY", "TOOLNET_MODEL", "TOOLNET_AI_ENABLED",
    "FASTSAVER_BASE_URL", "FASTSAVER_API_KEY",
    "FACEBOOK_MANUAL_RESOLVER", "MANUAL_FB_PROVIDER_BASE_URL", "MANUAL_FB_PROVIDER_API_KEY",
)
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
    settings.TOOLNET_BASE_URL = "https://toolnet.example.com/v1"
    settings.TOOLNET_API_KEY = "test_toolnet_key"
    settings.TOOLNET_MODEL = "test-model-v1"
    settings.TOOLNET_AI_ENABLED = True
    settings.FASTSAVER_BASE_URL = "https://fastsaver.example.com"
    settings.FASTSAVER_API_KEY = "test_fs_key"
    # Worker wiring tests use the legacy FastSaver path; the shortcut
    # adapter has its own mocked tests in test_manual_resolver.py.
    settings.FACEBOOK_MANUAL_RESOLVER = "fastsaver"
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


def seed_channel(pipe_id: str, did: str, channel: str, creds: bool = True) -> tuple[str, str]:
    async def _go():
        try:
            await pipelines.create_pipeline(pipeline_id=pipe_id, name=f"P {pipe_id}", slug=pipe_id)
        except Exception:
            pass
        try:
            await sources.create_source(
                source_id=f"{pipe_id}_src", pipeline_id=pipe_id, page_id="111",
                reels_url="https://www.facebook.com/111/reels/",
            )
        except Exception:
            pass
        await destinations.create_destination(
            destination_id=did, pipeline_id=pipe_id, channel_id="UC_" + did,
            channel_name=channel, visibility="public", enabled=True,
        )
        await destinations.set_connected(did, channel_id="UC_" + did, channel_name=channel)
        if creds:
            await youtube_auth.save_credentials(did, CREDS)

    asyncio.run(_go())
    return pipe_id, did


# ---------- A/B: list connected channels, safe fields ----------


def test_list_connected_destinations_safe_fields() -> None:
    seed_channel("pl_m1", "ytd_m1", "Channel A")
    seed_channel("pl_m1", "ytd_m2", "Channel B", creds=False)
    seed_channel("pl_m2", "ytd_m3", "Channel C")
    client = TestClient(create_app())
    r = client.get("/api/facebook/youtube-destinations", headers=AUTH_HEADERS)
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) >= 3
    by_name = {x["channel_name"]: x for x in items}
    assert by_name["Channel A"]["pipeline_id"] == "pl_m1"
    assert by_name["Channel C"]["pipeline_id"] == "pl_m2"
    blob = json.dumps(items).lower()
    for secret in ("ya29", "refresh_token", "client_secret", "credentials_json", "download_url", "api_key"):
        assert secret not in blob


# ---------- C/D: resolve, no download URL leak ----------


def test_resolve_rejects_profile_url() -> None:
    client = TestClient(create_app())
    r = client.post(
        "/api/facebook/manual/resolve", headers=AUTH_HEADERS,
        json={"url": "https://www.facebook.com/somepage"},
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"] == "MANUAL_INVALID_URL"


def test_resolve_returns_safe_preview_only() -> None:
    from app.services import facebook_manual_media as manual_media

    async def _fake_resolve(url, transport=None):
        return manual_media.ManualResolvedMedia(
            source_url=url, download_url="https://cdn.example.com/video.mp4",
            caption="Caption gốc từ Facebook",
            thumbnail_url="https://cdn.example.com/thumb.jpg",
            duration=12.5, provider="shortcut",
        )

    import app.routes.manual as manual_routes

    orig = manual_routes.resolve_manual_media
    manual_routes.resolve_manual_media = _fake_resolve
    try:
        client = TestClient(create_app())
        r = client.post(
            "/api/facebook/manual/resolve", headers=AUTH_HEADERS,
            json={"url": VIDEO_URL},
        )
    finally:
        manual_routes.resolve_manual_media = orig
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["caption"] == "Caption gốc từ Facebook"
    assert body["thumbnail_url"] == "https://cdn.example.com/thumb.jpg"
    blob = json.dumps(body).lower()
    assert "download_url" not in blob
    assert "cdn.example.com/video.mp4" not in blob


# ---------- E: AI metadata via owning pipeline settings ----------


def test_generate_manual_metadata_uses_pipeline_settings() -> None:
    from app.db.repositories import ai_settings as ai_settings_repo

    seed_channel("pl_m4", "ytd_m4", "Channel D")

    async def _save():
        return await ai_settings_repo.upsert_settings(
            pipeline_id="pl_m4", enabled=True, system_prompt="ỉn nờ",
            title_template="{title}", description_template="{description}\n\n{hashtags}",
            locked_hashtags=["#locked"], language="vi", model=settings.TOOLNET_MODEL,
        )

    asyncio.run(_save())
    out = asyncio.run(generate_manual_metadata(
        pipeline_id="pl_m4", caption="một chú mèo", source_url=VIDEO_URL,
        transport=toolnet_transport(),
    ))
    assert out["title"]
    assert "#locked" in out["hashtags"]
    assert out["model"] == "test-model-v1"


# ---------- F/G/H: publish flow mocked ----------


def _stage_job(pipe_id: str, did: str, publish_at=None) -> str:
    async def _go():
        row = await manual_repo.create_manual_publication(
            destination_id=did, pipeline_id=pipe_id, source_url=VIDEO_URL,
            caption="cap", thumbnail_url=None, duration=10.0,
            title="Tieu de", description="Mo ta", hashtags=["#a"],
            visibility="public" if publish_at is None else "private",
            publish_at=publish_at,
        )
        claimed = await manual_repo.claim_next_manual_job()
        assert claimed is not None and claimed["id"] == row["id"]
        return row["id"]

    return asyncio.run(_go())


def test_immediate_publish_mocked_end_to_end() -> None:
    pipe_id, did = seed_channel("pl_m5", "ytd_m5", "Channel E")
    mid = _stage_job(pipe_id, did)
    result = asyncio.run(process_manual_job(
        asyncio.run(manual_repo.get_manual_publication(mid)),
        transport=fastsaver_transport(), youtube_factory=fake_youtube_factory,
    ))
    assert result["result"] == "published", result
    assert result["youtube_video_id"] == "yt_manual_123"
    row = asyncio.run(manual_repo.get_manual_publication(mid))
    assert row is not None and row["status"] == "published"


def test_scheduled_publish_mocked() -> None:
    pipe_id, did = seed_channel("pl_m6", "ytd_m6", "Channel F")
    mid = _stage_job(pipe_id, did, publish_at="2030-01-01T00:00:00Z")
    job = asyncio.run(manual_repo.get_manual_publication(mid))
    assert job is not None and job["status"] == "processing"
    result = asyncio.run(process_manual_job(
        job, transport=fastsaver_transport(), youtube_factory=fake_youtube_factory,
    ))
    assert result["result"] == "scheduled", result
    row = asyncio.run(manual_repo.get_manual_publication(mid))
    assert row is not None and row["status"] == "scheduled"
    assert row["youtube_video_id"] == "yt_manual_123"


def test_tmp_cleanup_after_process() -> None:
    from app.services.facebook_media import TMP_ROOT

    pipe_id, did = seed_channel("pl_m7", "ytd_m7", "Channel G")
    mid = _stage_job(pipe_id, did)
    job = asyncio.run(manual_repo.get_manual_publication(mid))
    assert job is not None
    asyncio.run(process_manual_job(
        job, transport=fastsaver_transport(), youtube_factory=fake_youtube_factory,
    ))
    leftovers = [p for p in TMP_ROOT.glob("manual_mpub_*")]
    assert leftovers == [], leftovers


# ---------- I/J: duplicate protection ----------


def test_duplicate_blocked_then_forced() -> None:
    seed_channel("pl_m8", "ytd_m8", "Channel H")
    client = TestClient(create_app())
    payload = {
        "destination_id": "ytd_m8", "source_url": VIDEO_URL,
        "title": "T", "description": "D", "hashtags": ["#a"],
        "visibility": "public",
    }
    r1 = client.post("/api/facebook/manual/publish", headers=AUTH_HEADERS, json=payload)
    assert r1.status_code == 202, r1.text
    r2 = client.post("/api/facebook/manual/publish", headers=AUTH_HEADERS, json=payload)
    assert r2.status_code == 409, r2.text
    assert r2.json()["error"] == "DUPLICATE_VIDEO"
    assert r2.json()["existing_id"] == r1.json()["id"]
    r3 = client.post("/api/facebook/manual/publish", headers=AUTH_HEADERS,
                     json={**payload, "force_duplicate": True})
    assert r3.status_code == 202, r3.text
    assert r3.json()["id"] != r1.json()["id"]


# ---------- K: credential isolation ----------


def test_destination_without_credentials_rejected() -> None:
    seed_channel("pl_m9", "ytd_m9a", "Channel I", creds=True)
    seed_channel("pl_m9", "ytd_m9b", "Channel J", creds=False)
    client = TestClient(create_app())
    payload = {
        "destination_id": "ytd_m9b", "source_url": VIDEO_URL,
        "title": "T", "description": "D", "hashtags": [],
        "visibility": "public",
    }
    r = client.post("/api/facebook/manual/publish", headers=AUTH_HEADERS, json=payload)
    assert r.status_code == 400, r.text
    assert r.json()["error"] == "YOUTUBE_AUTH_FAILED"
    # The healthy channel is unaffected.
    payload["destination_id"] = "ytd_m9a"
    ok = client.post("/api/facebook/manual/publish", headers=AUTH_HEADERS, json=payload)
    assert ok.status_code == 202, ok.text


# ---------- M/N: shared loop order + failed jobs never stick ----------


def test_manual_claimed_before_auto_and_failures_terminal() -> None:
    seed_channel("pl_m10", "ytd_m10", "Channel K")

    async def _go():
        mrow = await manual_repo.create_manual_publication(
            destination_id="ytd_m10", pipeline_id="pl_m10", source_url=VIDEO_URL,
            caption=None, thumbnail_url=None, duration=None,
            title="T", description="D", hashtags=[], visibility="public",
            publish_at=None,
        )
        qid = await publish_queue.enqueue_publish_job(
            pipeline_id="pl_m10", destination_id="ytd_m10",
            reel_db_id="pl_m10_r9", publication_id="pub_auto_9", priority=0,
        )
        first = await manual_repo.claim_next_manual_job()
        assert first is not None and first["id"] == mrow["id"]
        # A failed manual job is terminal: the next claim finds nothing,
        # so the shared loop moves on instead of spinning.
        await manual_repo.mark_failed(mrow["id"], "MEDIA_RESOLVE_FAILED", "boom")
        assert await manual_repo.claim_next_manual_job() is None
        return qid

    asyncio.run(_go())
