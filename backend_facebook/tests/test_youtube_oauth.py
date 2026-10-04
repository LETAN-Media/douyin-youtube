import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.db.client as client_module
from app.config import settings
from app.db.client import migrate
from app.db.repositories import destinations, pipelines, youtube_auth
from app.main import create_app
from app.services import facebook_youtube_oauth as yt_oauth

TEST_DB_PATH = Path("/tmp/backend_facebook_task7a_test.db")
TEST_DB_URL = f"file:{TEST_DB_PATH}"
ADMIN = "test_admin_token"
AUTH_HEADERS = {"X-Admin-Token": ADMIN}


def fresh_db() -> None:
    client_module._client = None
    os.environ["ADMIN_TOKEN"] = ADMIN
    os.environ["TURSO_DATABASE_URL"] = TEST_DB_URL
    os.environ["TURSO_AUTH_TOKEN"] = "test_token"
    settings.ADMIN_TOKEN = ADMIN
    settings.TURSO_DATABASE_URL = TEST_DB_URL
    settings.TURSO_AUTH_TOKEN = "test_token"
    settings.GOOGLE_CLIENT_ID = "test-google-client-id"
    settings.GOOGLE_CLIENT_SECRET = "test-google-client-secret"
    settings.FACEBOOK_YOUTUBE_CALLBACK_URL = "https://fb.example.com/api/facebook/youtube/oauth/callback"
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
        "admin": os.environ.get("ADMIN_TOKEN"),
        "settings_url": settings.TURSO_DATABASE_URL,
        "gid": settings.GOOGLE_CLIENT_ID,
        "gsecret": settings.GOOGLE_CLIENT_SECRET,
        "cb": settings.FACEBOOK_YOUTUBE_CALLBACK_URL,
    }
    fresh_db()
    yield
    client_module._client = None
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    if prev["url"] is not None:
        os.environ["TURSO_DATABASE_URL"] = prev["url"]
    if prev["admin"] is not None:
        os.environ["ADMIN_TOKEN"] = prev["admin"]
    settings.TURSO_DATABASE_URL = prev["settings_url"]
    settings.GOOGLE_CLIENT_ID = prev["gid"]
    settings.GOOGLE_CLIENT_SECRET = prev["gsecret"]
    settings.FACEBOOK_YOUTUBE_CALLBACK_URL = prev["cb"]
    client_module._client = None


def _setup_pipeline_with_destination(pid: str = "pl_yt", did: str = "ytd_1"):
    async def _go():
        await pipelines.create_pipeline(pipeline_id=pid, name="YT", slug=pid)
        return await destinations.create_destination(destination_id=did, pipeline_id=pid)

    return asyncio.run(_go())


class FakeCredentials:
    def __init__(self, refresh_token=None):
        self.token = "ya29.new-access"
        self.refresh_token = refresh_token
        self.token_uri = "https://oauth2.googleapis.com/token"
        self.client_id = "test-google-client-id"
        self.client_secret = "test-google-client-secret"
        self.scopes = list(yt_oauth.SCOPES)


class FakeFlow:
    instances: list = []

    def __init__(self, refresh_token=None, fetch_error=None, scopes=None):
        self.credentials = FakeCredentials(refresh_token)
        if scopes is not None:
            self.credentials.scopes = scopes
        self.redirect_uri = None
        self.fetch_kwargs: dict = {}
        self._fetch_error = fetch_error
        FakeFlow.instances.append(self)

    def fetch_token(self, **kwargs):
        self.fetch_kwargs = kwargs
        if self._fetch_error is not None:
            raise self._fetch_error
        return None


def _future_expires() -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=14)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_oauth_start_creates_state(db) -> None:
    _setup_pipeline_with_destination()
    url = asyncio.run(yt_oauth.create_authorization_url("ytd_1", "pl_yt"))
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "access_type=offline" in url
    assert "select_account" in url
    assert "youtube.upload" in url

    async def _check():
        from app.db.client import get_client

        rows = await get_client().execute("SELECT state, destination_id, pipeline_id FROM youtube_oauth_states")
        return rows.rows

    rows = asyncio.run(_check())
    assert len(rows) == 1
    assert rows[0][1] == "ytd_1" and rows[0][2] == "pl_yt"


def test_oauth_start_rejects_foreign_destination(db) -> None:
    _setup_pipeline_with_destination(pid="pl_a", did="ytd_a")

    async def _other():
        await pipelines.create_pipeline(pipeline_id="pl_b", name="B", slug="pl_b")

    asyncio.run(_other())
    with pytest.raises(RuntimeError):
        asyncio.run(yt_oauth.create_authorization_url("ytd_a", "pl_b"))


def test_callback_success_saves_channel(db) -> None:
    _setup_pipeline_with_destination()

    async def _mkstate():
        await youtube_auth.create_oauth_state(
            state="st_ok", destination_id="ytd_1", pipeline_id="pl_yt", expires_at=_future_expires()
        )

    asyncio.run(_mkstate())
    info = asyncio.run(
        yt_oauth.complete_oauth(
            "st_ok",
            "authcode_abc",
            flow_factory=lambda state: FakeFlow(refresh_token="rt_new"),
            channel_fetcher=lambda flow: ("UC123", "My Channel"),
        )
    )
    assert info == {
        "destination_id": "ytd_1",
        "pipeline_id": "pl_yt",
        "channel_id": "UC123",
        "channel_name": "My Channel",
    }
    dest = asyncio.run(destinations.get_destination("ytd_1"))
    assert dest["connected"] is True
    assert dest["channel_id"] == "UC123" and dest["channel_name"] == "My Channel"
    creds = json.loads(asyncio.run(youtube_auth.get_credentials("ytd_1")))
    assert creds["refresh_token"] == "rt_new"
    assert asyncio.run(youtube_auth.get_oauth_state("st_ok")) is None  # one-time use


def test_expired_state_rejected_and_deleted(db) -> None:
    _setup_pipeline_with_destination()
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    async def _mkstate():
        await youtube_auth.create_oauth_state(
            state="st_old", destination_id="ytd_1", pipeline_id="pl_yt", expires_at=past
        )

    asyncio.run(_mkstate())
    with pytest.raises(RuntimeError, match="expired"):
        asyncio.run(yt_oauth.complete_oauth("st_old", "authcode_1"))
    assert asyncio.run(youtube_auth.get_oauth_state("st_old")) is None


def test_invalid_state_rejected(db) -> None:
    with pytest.raises(RuntimeError, match="not exist"):
        asyncio.run(yt_oauth.complete_oauth("nope", "authcode_1"))


def test_destination_mismatch_rejected(db) -> None:
    _setup_pipeline_with_destination(pid="pl_a", did="ytd_a")

    async def _other():
        await pipelines.create_pipeline(pipeline_id="pl_b", name="B", slug="pl_b")
        await destinations.create_destination(destination_id="ytd_b", pipeline_id="pl_b")

    asyncio.run(_other())

    async def _mkstate():
        await youtube_auth.create_oauth_state(
            state="st_mm", destination_id="ytd_b", pipeline_id="pl_b", expires_at=_future_expires()
        )

    asyncio.run(_mkstate())
    # tamper: state says ytd_b/pl_b but complete against nothing else is possible;
    # simulate destination moved pipelines by editing destination's pipeline
    from app.db.client import get_client

    async def _move():
        await get_client().execute(
            "UPDATE youtube_destinations SET pipeline_id = 'pl_a' WHERE id = 'ytd_b'"
        )

    asyncio.run(_move())
    with pytest.raises(RuntimeError, match="match"):
        asyncio.run(yt_oauth.complete_oauth("st_mm", "authcode_1"))


def test_reconnect_preserves_own_refresh_token(db) -> None:
    _setup_pipeline_with_destination()

    async def _seed():
        await youtube_auth.create_oauth_state(
            state="st_r1", destination_id="ytd_1", pipeline_id="pl_yt", expires_at=_future_expires()
        )

    asyncio.run(_seed())
    asyncio.run(
        yt_oauth.complete_oauth(
            "st_r1", "authcode_1",
            flow_factory=lambda state: FakeFlow(refresh_token="rt_first"),
            channel_fetcher=lambda flow: ("UC123", "My Channel"),
        )
    )

    async def _seed2():
        await youtube_auth.create_oauth_state(
            state="st_r2", destination_id="ytd_1", pipeline_id="pl_yt", expires_at=_future_expires()
        )

    asyncio.run(_seed2())
    asyncio.run(
        yt_oauth.complete_oauth(
            "st_r2", "authcode_2",
            flow_factory=lambda state: FakeFlow(refresh_token=None),  # Google omits new token
            channel_fetcher=lambda flow: ("UC123", "My Channel"),
        )
    )
    creds = json.loads(asyncio.run(youtube_auth.get_credentials("ytd_1")))
    assert creds["refresh_token"] == "rt_first"


def test_credentials_never_cross_destinations(db) -> None:
    _setup_pipeline_with_destination(pid="pl_a", did="ytd_a")

    async def _other():
        await pipelines.create_pipeline(pipeline_id="pl_b", name="B", slug="pl_b")
        await destinations.create_destination(destination_id="ytd_b", pipeline_id="pl_b")
        await youtube_auth.create_oauth_state(
            state="st_cross", destination_id="ytd_b", pipeline_id="pl_b", expires_at=_future_expires()
        )
        await youtube_auth.save_credentials("ytd_a", json.dumps({"refresh_token": "rt_A"}))

    asyncio.run(_other())
    asyncio.run(
        yt_oauth.complete_oauth(
            "st_cross", "authcode_1",
            flow_factory=lambda state: FakeFlow(refresh_token=None),
            channel_fetcher=lambda flow: ("UC_B", "Channel B"),
        )
    )
    creds_b = json.loads(asyncio.run(youtube_auth.get_credentials("ytd_b")))
    # decisive: B must NOT inherit A's refresh token through any fallback
    assert creds_b.get("refresh_token") is None
    dest_b = asyncio.run(destinations.get_destination("ytd_b"))
    assert dest_b["channel_id"] == "UC_B"
    # and A's credentials are untouched
    creds_a = json.loads(asyncio.run(youtube_auth.get_credentials("ytd_a")))
    assert creds_a.get("refresh_token") == "rt_A"


def test_api_hides_secrets(db) -> None:
    _setup_pipeline_with_destination()

    async def _seed():
        await youtube_auth.save_credentials("ytd_1", json.dumps({"refresh_token": "rt_x", "token": "t"}))
        await destinations.set_connected("ytd_1", channel_id="UC1", channel_name="C1")

    asyncio.run(_seed())
    client = TestClient(create_app())
    r = client.get("/api/facebook/pipelines/pl_yt/youtube-destinations")
    assert r.status_code == 200
    body = r.json()[0]
    assert body["connected"] is True and body["channel_id"] == "UC1"
    blob = json.dumps(body)
    assert "refresh_token" not in blob and "rt_x" not in blob
    assert "GOOGLE_CLIENT_SECRET" not in blob and "test-google-client-secret" not in blob


def test_endpoints_auth_and_flow(db) -> None:
    _setup_pipeline_with_destination()
    client = TestClient(create_app())
    r = client.post("/api/facebook/pipelines/pl_yt/youtube-destinations", json={})
    assert r.status_code == 401
    r = client.post(
        "/api/facebook/pipelines/pl_yt/youtube-destinations", json={}, headers=AUTH_HEADERS
    )
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    assert r.json()["connected"] is False

    r = client.post(
        f"/api/facebook/youtube-destinations/{did}/oauth/start", headers=AUTH_HEADERS
    )
    assert r.status_code == 200, r.text
    assert r.json()["authorization_url"].startswith("https://accounts.google.com/")

    r = client.get("/api/facebook/youtube/oauth/callback")
    assert r.status_code == 400

    r = client.get("/api/facebook/youtube/oauth/callback?state=bad&code=1")
    assert r.status_code == 400
    assert r.json()["error"] == "OAUTH_INVALID_STATE"


def test_missing_google_config_fail_fast(db, monkeypatch) -> None:
    import app.services.facebook_youtube_oauth as mod

    monkeypatch.setattr(mod.settings, "GOOGLE_CLIENT_ID", "")
    with pytest.raises(RuntimeError, match="GOOGLE_CLIENT_ID"):
        mod.validate_google_config()
    with pytest.raises(RuntimeError):
        asyncio.run(mod.create_authorization_url("ytd_1", "pl_yt"))


class ProviderError(Exception):
    def __init__(self, error: str, description: str = ""):
        super().__init__(f"({error}) {description}")
        self.error = error


def _mkstate_sync(state: str, did: str = "ytd_1", pid: str = "pl_yt"):
    async def _go():
        await youtube_auth.create_oauth_state(
            state=state, destination_id=did, pipeline_id=pid, expires_at=_future_expires()
        )

    asyncio.run(_go())


def test_fetch_uses_code_directly_and_env_redirect(db) -> None:
    _setup_pipeline_with_destination()
    _mkstate_sync("st_code")
    FakeFlow.instances.clear()
    asyncio.run(
        yt_oauth.complete_oauth(
            "st_code", "authcode_xyz",
            flow_factory=lambda state: FakeFlow(refresh_token="rt"),
            channel_fetcher=lambda flow: ("UC1", "C1"),
        )
    )
    flow = FakeFlow.instances[-1]
    assert flow.fetch_kwargs.get("code") == "authcode_xyz"
    assert "authorization_response" not in flow.fetch_kwargs
    assert flow.redirect_uri == "https://fb.example.com/api/facebook/youtube/oauth/callback"


def test_reverse_proxy_url_cannot_affect_exchange(db, monkeypatch) -> None:
    """Route no longer receives Request: forged Host/scheme can't leak into OAuth."""
    import app.routes.youtube as route_mod

    _setup_pipeline_with_destination()
    _mkstate_sync("st_proxy")
    seen: dict = {}

    async def _fake_complete(state: str, code: str):
        seen["state"] = state
        seen["code"] = code
        return {"destination_id": "ytd_1", "pipeline_id": "pl_yt",
                "channel_id": "UC9", "channel_name": "Proxy Chan"}

    monkeypatch.setattr(route_mod.yt_oauth, "complete_oauth", _fake_complete)
    client = TestClient(create_app())
    r = client.get(
        "/api/facebook/youtube/oauth/callback?state=st_proxy&code=proxycode123",
        headers={"Host": "evil.example.com", "X-Forwarded-Proto": "http"},
    )
    assert r.status_code == 200, r.text
    assert seen == {"state": "st_proxy", "code": "proxycode123"}
    assert "evil.example.com" not in r.text


def test_invalid_client_safe_error(db) -> None:
    _setup_pipeline_with_destination()
    _mkstate_sync("st_ic")
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            yt_oauth.complete_oauth(
                "st_ic", "authcode_1",
                flow_factory=lambda state: FakeFlow(
                    fetch_error=ProviderError("invalid_client", "Unauthorized")),
            )
        )
    assert "provider_error=invalid_client" in str(exc.value)
    assert "test-google-client-secret" not in str(exc.value)
    assert "authcode_1" not in str(exc.value)


def test_redirect_uri_mismatch_safe_error(db) -> None:
    _setup_pipeline_with_destination()
    _mkstate_sync("st_ru")
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            yt_oauth.complete_oauth(
                "st_ru", "authcode_1",
                flow_factory=lambda state: FakeFlow(
                    fetch_error=ProviderError("redirect_uri_mismatch", "Bad redirect")),
            )
        )
    assert "provider_error=redirect_uri_mismatch" in str(exc.value)


def test_extra_granted_scopes_accepted(db) -> None:
    _setup_pipeline_with_destination()
    _mkstate_sync("st_extra")
    info = asyncio.run(
        yt_oauth.complete_oauth(
            "st_extra", "authcode_1",
            flow_factory=lambda state: FakeFlow(
                refresh_token="rt",
                scopes=list(yt_oauth.SCOPES) + [
                    "https://www.googleapis.com/auth/youtube.force-ssl",
                    "https://www.googleapis.com/auth/yt-analytics.readonly",
                ],
            ),
            channel_fetcher=lambda flow: ("UC_E", "Extra"),
        )
    )
    assert info["channel_id"] == "UC_E"
    dest = asyncio.run(destinations.get_destination("ytd_1"))
    assert dest["connected"] is True


def test_missing_upload_scope_rejected(db) -> None:
    _setup_pipeline_with_destination()
    _mkstate_sync("st_nup")
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            yt_oauth.complete_oauth(
                "st_nup", "authcode_1",
                flow_factory=lambda state: FakeFlow(
                    refresh_token="rt",
                    scopes=["https://www.googleapis.com/auth/youtube.readonly"],
                ),
                channel_fetcher=lambda flow: ("UC_X", "X"),
            )
        )
    assert "youtube.upload" in str(exc.value)
    assert asyncio.run(destinations.get_destination("ytd_1"))["connected"] is False


def test_missing_readonly_scope_rejected(db) -> None:
    _setup_pipeline_with_destination()
    _mkstate_sync("st_nro")
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            yt_oauth.complete_oauth(
                "st_nro", "authcode_1",
                flow_factory=lambda state: FakeFlow(
                    refresh_token="rt",
                    scopes=["https://www.googleapis.com/auth/youtube.upload"],
                ),
                channel_fetcher=lambda flow: ("UC_X", "X"),
            )
        )
    assert "youtube.readonly" in str(exc.value)


def test_missing_code_rejected(db) -> None:
    _setup_pipeline_with_destination()
    _mkstate_sync("st_nc")
    with pytest.raises(RuntimeError, match="code is missing"):
        asyncio.run(yt_oauth.complete_oauth("st_nc", "  "))
    client = TestClient(create_app())
    r = client.get("/api/facebook/youtube/oauth/callback?state=st_nc&code=")
    assert r.status_code == 400


def test_no_secret_code_token_in_error_paths(db, caplog) -> None:
    import logging

    _setup_pipeline_with_destination()
    _mkstate_sync("st_leak")
    with caplog.at_level(logging.WARNING):
        with pytest.raises(RuntimeError) as exc:
            asyncio.run(
                yt_oauth.complete_oauth(
                    "st_leak", "supersecretcode123",
                    flow_factory=lambda state: FakeFlow(
                        fetch_error=ProviderError("invalid_grant", "Bad code")),
                )
            )
    blob = str(exc.value) + caplog.text
    for secret in ("supersecretcode123", "test-google-client-secret", "ya29.new-access"):
        assert secret not in blob, secret
    assert "provider_error=invalid_grant" in str(exc.value)
