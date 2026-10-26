import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import app.db.client as client_module
from app.config import settings
from app.db.client import migrate
from app.db.repositories import destinations, pipelines, youtube_auth, reels
from app.main import create_app
from app.services import youtube_oauth as yt_oauth

TEST_DB_PATH = Path("/tmp/backend_tiktok_youtube_test.db")
TEST_DB_URL = f"file:{TEST_DB_PATH}"
ADMIN = "test_admin_token"
AUTH_HEADERS = {"Authorization": f"Bearer {ADMIN}", "X-Admin-Token": ADMIN}


def fresh_db() -> None:
    client_module._client = None
    os.environ["ADMIN_TOKEN"] = ADMIN
    os.environ["TURSO_DATABASE_URL"] = TEST_DB_URL
    os.environ["TURSO_AUTH_TOKEN"] = "test_token"
    settings.admin_token = ADMIN
    settings.turso_database_url = TEST_DB_URL
    settings.turso_auth_token = "test_token"
    settings.google_client_id = "test-google-client-id"
    settings.google_client_secret = "test-google-client-secret"
    settings.tiktok_youtube_callback_url = "https://tiktok-api.toolnet.tech/api/tiktok/youtube/oauth/callback"
    settings.dashboard_base_url = "https://douyin.toolnet.tech"
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    for suffix in ("-wal", "-shm", "-journal"):
        p = Path(str(TEST_DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    asyncio.run(migrate())


@pytest.fixture()
def db():
    fresh_db()
    yield
    client_module._client = None
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


def dummy_flow(
    state: str,
    *,
    token: str = "tok_new",
    refresh_token: str | None = "ref_new",
    scopes: list[str] | None = None,
):
    credentials = SimpleNamespace(
        token=token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id="test-client-id",
        client_secret="test-client-secret",
        scopes=scopes or list(yt_oauth.SCOPES),
    )
    flow = MagicMock()
    flow.state = state
    flow.credentials = credentials
    flow.fetch_token = MagicMock()
    return flow


@pytest.mark.asyncio
async def test_sanitize_return_to():
    assert yt_oauth.sanitize_return_to("/tiktok/pipe-1") == "/tiktok/pipe-1"
    assert yt_oauth.sanitize_return_to("/tiktok/pipe-1?tab=destinations") == "/tiktok/pipe-1?tab=destinations"
    assert yt_oauth.sanitize_return_to("https://evil.com") is None
    assert yt_oauth.sanitize_return_to("//evil.com") is None
    assert yt_oauth.sanitize_return_to("/facebook/pipe-1") is None
    assert yt_oauth.sanitize_return_to(None) is None


@pytest.mark.asyncio
async def test_build_auth_url_and_state(db):
    pipe = await pipelines.create_pipeline("pipe_1", "Pipeline 1", "pipeline-1")
    dest = await destinations.create_destination("dest_1", pipe["id"])

    url, state = await yt_oauth.build_auth_url(dest["id"], pipe["id"], return_to="/tiktok/pipeline-1")
    assert "https://accounts.google.com" in url
    assert state in url

    stored = await youtube_auth.get_oauth_state(state)
    assert stored is not None
    assert stored["destination_id"] == dest["id"]
    assert stored["pipeline_id"] == pipe["id"]
    assert stored["return_to"] == "/tiktok/pipeline-1"


@pytest.mark.asyncio
async def test_build_auth_url_tenant_isolation(db):
    pipe_a = await pipelines.create_pipeline("pipe_a", "Pipeline A", "pipe-a")
    pipe_b = await pipelines.create_pipeline("pipe_b", "Pipeline B", "pipe-b")
    dest_a = await destinations.create_destination("dest_a", pipe_a["id"])

    # Attempting to start OAuth with dest_a under pipe_b must fail
    with pytest.raises(RuntimeError, match="Destination does not belong to this pipeline"):
        await yt_oauth.build_auth_url(dest_a["id"], pipe_b["id"])


@pytest.mark.asyncio
async def test_complete_oauth_success_and_single_use(db):
    pipe = await pipelines.create_pipeline("pipe_1", "Pipeline 1", "pipeline-1")
    dest = await destinations.create_destination("dest_1", pipe["id"])

    _, state = await yt_oauth.build_auth_url(dest["id"], pipe["id"], return_to="/tiktok/pipe-1")

    flow = dummy_flow(state, token="access_123", refresh_token="refresh_123")
    channel_fetcher = lambda f: ("UC_test_chan_123", "Test TikTok Channel", "https://avatar.url/pic.jpg")

    info = await yt_oauth.handle_callback(
        code="auth_code_xyz",
        state=state,
        flow_factory=lambda s: flow,
        channel_fetcher=channel_fetcher,
    )

    assert info["destination_id"] == dest["id"]
    assert info["channel_id"] == "UC_test_chan_123"
    assert info["channel_name"] == "Test TikTok Channel"
    assert info["channel_avatar_url"] == "https://avatar.url/pic.jpg"
    assert info["return_to"] == "/tiktok/pipe-1"

    # Destination in DB updated to connected with channel metadata
    updated_dest = await destinations.get_destination(dest["id"])
    assert updated_dest["connected"] is True
    assert updated_dest["channel_id"] == "UC_test_chan_123"
    assert updated_dest["channel_name"] == "Test TikTok Channel"
    assert updated_dest["channel_avatar_url"] == "https://avatar.url/pic.jpg"
    assert updated_dest["is_default"] is True  # auto-marked default

    # Credentials saved
    creds_row = await youtube_auth.get_credentials(dest["id"])
    assert creds_row is not None
    creds_data = json.loads(creds_row["credentials_json"])
    assert creds_data["token"] == "access_123"
    assert creds_data["refresh_token"] == "refresh_123"

    # Replay attack: using the same state again MUST fail because state was consumed
    with pytest.raises(RuntimeError, match="OAuth state does not exist or has already been used"):
        await yt_oauth.handle_callback(
            code="auth_code_xyz",
            state=state,
            flow_factory=lambda s: flow,
            channel_fetcher=channel_fetcher,
        )


@pytest.mark.asyncio
async def test_complete_oauth_preserves_old_refresh_token(db):
    pipe = await pipelines.create_pipeline("pipe_1", "Pipeline 1", "pipeline-1")
    dest = await destinations.create_destination("dest_1", pipe["id"])

    # Pre-existing credentials with refresh token
    await youtube_auth.save_credentials(
        dest["id"],
        json.dumps({
            "token": "old_token",
            "refresh_token": "original_refresh_token",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "cid",
            "client_secret": "csec",
            "scopes": list(yt_oauth.SCOPES),
        }),
    )

    _, state = await yt_oauth.build_auth_url(dest["id"], pipe["id"])

    # Google omits refresh_token on re-consent
    flow = dummy_flow(state, token="new_access_token", refresh_token=None)
    channel_fetcher = lambda f: ("UC_test_chan_123", "Test Channel", None)

    await yt_oauth.handle_callback(
        code="auth_code_2",
        state=state,
        flow_factory=lambda s: flow,
        channel_fetcher=channel_fetcher,
    )

    creds_row = await youtube_auth.get_credentials(dest["id"])
    creds_data = json.loads(creds_row["credentials_json"])
    assert creds_data["token"] == "new_access_token"
    assert creds_data["refresh_token"] == "original_refresh_token"


@pytest.mark.asyncio
async def test_complete_oauth_expired_state(db):
    pipe = await pipelines.create_pipeline("pipe_1", "Pipeline 1", "pipeline-1")
    dest = await destinations.create_destination("dest_1", pipe["id"])

    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = "expired_state_123"
    await youtube_auth.create_oauth_state(state, dest["id"], pipe["id"], past)

    with pytest.raises(RuntimeError, match="OAuth state has expired"):
        await yt_oauth.handle_callback(
            code="code",
            state=state,
            flow_factory=lambda s: dummy_flow(s),
            channel_fetcher=lambda f: ("ch", "name", None),
        )


@pytest.mark.asyncio
async def test_multi_destination_management(db):
    pipe = await pipelines.create_pipeline("pipe_1", "Pipeline 1", "pipeline-1")

    # 1. First destination is created, marked default automatically
    d1 = await destinations.create_destination("dest_1", pipe["id"], channel_name="Channel 1")
    assert d1["is_default"] is True
    assert d1["enabled"] is True

    # 2. Second destination is created, not default
    d2 = await destinations.create_destination("dest_2", pipe["id"], channel_name="Channel 2")
    assert d2["is_default"] is False

    # 3. List destinations returns d1 first (is_default DESC)
    dests = await destinations.list_destinations(pipe["id"])
    assert len(dests) == 2
    assert dests[0]["id"] == "dest_1"
    assert dests[1]["id"] == "dest_2"

    # 4. Set d2 as default -> d1 is no longer default
    await destinations.set_default_destination(pipe["id"], "dest_2")
    d1_updated = await destinations.get_destination("dest_1")
    d2_updated = await destinations.get_destination("dest_2")
    assert d1_updated["is_default"] is False
    assert d2_updated["is_default"] is True

    # 5. Toggle enabled
    await destinations.toggle_destination_enabled("dest_2", False)
    d2_disabled = await destinations.get_destination("dest_2")
    assert d2_disabled["enabled"] is False

    # 6. Disconnect destination
    await destinations.disconnect_destination("dest_2")
    d2_disc = await destinations.get_destination("dest_2")
    assert d2_disc["connected"] is False
    assert d2_disc["is_default"] is False


def test_oauth_routes_and_callback(db):
    app = create_app()
    client = TestClient(app)

    # 1. Create pipeline
    r_pipe = client.post(
        "/api/tiktok/pipelines/",
        json={"id": "pipe_api_1", "name": "Pipeline API", "slug": "pipe-api"},
        headers=AUTH_HEADERS,
    )
    assert r_pipe.status_code == 200
    pipe_id = r_pipe.json()["id"]

    # 2. Start OAuth endpoint
    r_start = client.post(
        "/api/tiktok/youtube/oauth/start",
        json={"pipeline_id": pipe_id, "return_to": f"/tiktok/{pipe_id}?tab=destinations"},
        headers=AUTH_HEADERS,
    )
    assert r_start.status_code == 200
    start_data = r_start.json()
    assert "authorization_url" in start_data
    dest_id = start_data["destination_id"]
    state = start_data["state"]

    # 3. Callback endpoint WITHOUT admin token (Google redirects end-user browser)
    flow = dummy_flow(state)
    with patch("app.services.youtube_oauth._new_flow", return_value=flow), \
         patch("app.services.youtube_oauth._fetch_channel", return_value=("UC_mock", "Mock Channel", "https://avatar.url")):
        r_cb = client.get(
            f"/api/tiktok/youtube/oauth/callback?code=mock_code&state={state}",
            follow_redirects=False,
        )
        assert r_cb.status_code == 303
        location = r_cb.headers["location"]
        assert location == f"https://douyin.toolnet.tech/tiktok/{pipe_id}?tab=destinations&youtube_connected=1"

    # 4. Callback with Google error redirect (e.g. user denied)
    # Start another oauth
    r_start2 = client.post(
        "/api/tiktok/youtube/oauth/start",
        json={"pipeline_id": pipe_id, "return_to": f"/tiktok/{pipe_id}"},
        headers=AUTH_HEADERS,
    )
    state2 = r_start2.json()["state"]
    r_cb_err = client.get(
        f"/api/tiktok/youtube/oauth/callback?error=access_denied&state={state2}",
        follow_redirects=False,
    )
    assert r_cb_err.status_code == 303
    assert "youtube_error=access_denied" in r_cb_err.headers["location"]


@pytest.mark.asyncio
async def test_publish_routing_and_tenant_isolation(db):
    app = create_app()
    client = TestClient(app)

    pipe_a = await pipelines.create_pipeline("pipe_a", "Pipeline A", "pipe-a")
    pipe_b = await pipelines.create_pipeline("pipe_b", "Pipeline B", "pipe-b")

    # Destination on Pipe A, but NOT connected
    dest_a = await destinations.create_destination("dest_a", pipe_a["id"])

    # Reel on Pipe A
    source = await db_insert_source(pipe_a["id"], "citrachoighelam_19")
    reel_id, _, _ = await reels.insert_reel_if_new(source_id=source["id"], reel_id="reel_123", reel_url="https://tiktok.com/@u/video/123", caption="caption")

    # 1. Manual publish to unconnected destination fails
    r_manual = client.post(
        f"/api/tiktok/manual/{pipe_a['id']}/{dest_a['id']}",
        json={"source_url": "https://tiktok.com/@u/video/123"},
        headers=AUTH_HEADERS,
    )
    assert r_manual.status_code == 400
    assert "chưa kết nối OAuth" in r_manual.text

    # 2. Manual publish with destination from another pipeline fails with 404
    r_tenant = client.post(
        f"/api/tiktok/manual/{pipe_b['id']}/{dest_a['id']}",
        json={"source_url": "https://tiktok.com/@u/video/123"},
        headers=AUTH_HEADERS,
    )
    assert r_tenant.status_code == 404

    # Connect dest_a
    await destinations.set_destination_connected(dest_a["id"], "UC_1", "Channel 1")

    # 3. Disable dest_a -> manual publish fails
    await destinations.toggle_destination_enabled(dest_a["id"], False)
    r_disabled = client.post(
        f"/api/tiktok/manual/{pipe_a['id']}/{dest_a['id']}",
        json={"source_url": "https://tiktok.com/@u/video/123"},
        headers=AUTH_HEADERS,
    )
    assert r_disabled.status_code == 400
    assert "đang bị tắt" in r_disabled.text

    # 4. Auto publish route without destination: if no connected & enabled dest -> fails
    r_pub_fail = client.post(
        f"/api/tiktok/publish/pipeline/{pipe_a['id']}",
        json={"reel_db_id": reel_id},
        headers=AUTH_HEADERS,
    )
    assert r_pub_fail.status_code == 400
    assert "Pipeline chưa có kênh YouTube nào" in r_pub_fail.text

    # Enable dest_a -> auto publish succeeds and routes to dest_a
    await destinations.toggle_destination_enabled(dest_a["id"], True)
    r_pub_ok = client.post(
        f"/api/tiktok/publish/pipeline/{pipe_a['id']}",
        json={"reel_db_id": reel_id},
        headers=AUTH_HEADERS,
    )
    assert r_pub_ok.status_code == 200
    assert r_pub_ok.json()["status"] == "queued"


async def db_insert_source(pipeline_id: str, username: str) -> dict:
    from app.db.repositories import sources
    return await sources.create_source(f"src_{username}", pipeline_id, username)
