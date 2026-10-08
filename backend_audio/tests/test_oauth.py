"""OAuth regression: callback routing, real channel id, expiry, reconnect reuse."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

ADMIN = {"X-Admin-Token": "test_admin_token"}


@pytest.fixture()
def client(db, monkeypatch):
    from app.config import settings

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    settings.GOOGLE_CLIENT_ID = "test-client-id"
    settings.GOOGLE_CLIENT_SECRET = "test-secret"
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("AUDIO_TOKEN_ENCRYPTION_KEY", key)
    settings.AUDIO_TOKEN_ENCRYPTION_KEY = key
    return TestClient(create_app())


def _make_pipeline(client):
    return client.post("/api/audio/pipelines", headers=ADMIN,
                       json={"name": "P"}).json()["id"]


def test_oauth_start_uses_audio_callback(db, client):
    pid = _make_pipeline(client)
    r = client.post(f"/api/audio/youtube/oauth/start?pipeline_id={pid}",
                    headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    from urllib.parse import unquote

    decoded = unquote(body["authorization_url"])
    assert ("/api/audio/youtube/oauth/callback" in decoded
            and "/api/drama/" not in decoded)
    # Reconnect reuses the same unconnected destination (no duplicates).
    r2 = client.post(f"/api/audio/youtube/oauth/start?pipeline_id={pid}",
                     headers=ADMIN)
    assert r2.json()["destination_id"] == body["destination_id"]


def test_callback_stores_real_channel_id(db, client, monkeypatch):
    import app.routes.youtube as yt_routes
    from app.services import youtube_oauth as oauth

    pid = _make_pipeline(client)
    dest_id = client.post(
        f"/api/audio/youtube/oauth/start?pipeline_id={pid}",
        headers=ADMIN).json()["destination_id"]
    state = client.post(
        f"/api/audio/youtube/oauth/start?pipeline_id={pid}&destination_id={dest_id}",
        headers=ADMIN).json()

    async def fake_exchange(code: str):
        assert code == "auth-code-1"
        return {"refresh_token": "rt-1", "access_token": "at-1"}

    async def fake_channel(access_token: str):
        assert access_token == "at-1"
        return {"channel_id": "UC0123456789abcdef",
                "channel_title": "Kenh Test",
                "channel_thumbnail": "https://img/x.jpg"}

    monkeypatch.setattr(oauth, "exchange_code", fake_exchange)
    monkeypatch.setattr(yt_routes, "_resolve_channel", fake_channel)

    from app.services.youtube_oauth import start_oauth

    start_oauth(pid, dest_id)
    from app.db.client import get_client

    state = get_client().execute(
        "SELECT state FROM audio_oauth_states WHERE destination_id = ?",
        (dest_id,)).fetchone()["state"]
    r = client.get(
        f"/api/audio/youtube/oauth/callback?code=auth-code-1&state={state}",
        follow_redirects=False)
    assert r.status_code == 302
    assert "oauth=connected" in r.headers["location"]

    dests = client.get(f"/api/audio/pipelines/{pid}/youtube-destinations",
                       headers=ADMIN).json()
    dest = next(d for d in dests if d["id"] == dest_id)
    assert dest["connected"] is True
    # Real channel id (UC…), NOT the channel title.
    assert dest["channel_id"] == "UC0123456789abcdef"
    assert dest["channel_title"] == "Kenh Test"
    assert dest["channel_thumbnail"] == "https://img/x.jpg"

    # Refresh token is Fernet-encrypted at rest, decryptable with the key.
    creds = oauth.load_credentials(dest_id)
    assert creds["refresh_token"] == "rt-1"
    assert creds["channel_id"] == "UC0123456789abcdef"


def test_callback_rejects_expired_state(db, client):
    from app.db.client import get_client

    pid = _make_pipeline(client)
    dest_id = client.post(
        f"/api/audio/youtube/oauth/start?pipeline_id={pid}",
        headers=ADMIN).json()["destination_id"]
    get_client().execute(
        "INSERT INTO audio_oauth_states (state, destination_id, pipeline_id, "
        "expires_at) VALUES ('stale', ?, ?, '2000-01-01T00:00:00Z')",
        (dest_id, pid))
    get_client().commit()
    r = client.get("/api/audio/youtube/oauth/callback?code=x&state=stale",
                   follow_redirects=False)
    assert r.status_code == 302
    assert "oauth=error" in r.headers["location"]


def test_callback_missing_params_redirects_error(db, client):
    r = client.get("/api/audio/youtube/oauth/callback",
                   follow_redirects=False)
    assert r.status_code == 302
    assert "oauth=error" in r.headers["location"]
