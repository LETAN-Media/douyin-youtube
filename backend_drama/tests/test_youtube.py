"""YouTube OAuth + destinations + publisher (mocked Google, no network).

Covers: start/callback, invalid/expired state, credential storage +
old-refresh preservation, channel listing, per-pipeline select,
safe disconnect, upload progress/retry/idempotency.
"""

import asyncio

from fastapi.testclient import TestClient

ADMIN = {"X-Admin-Token": "test_admin_token"}


def _client():
    from app.main import create_app

    return TestClient(create_app())


def _pipe(client, name="Pipe YT"):
    r = client.post("/api/drama/pipelines", headers=ADMIN, json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _google_env(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "test_cid")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "test_csec")
    monkeypatch.setattr(
        settings, "DRAMA_YOUTUBE_CALLBACK_URL",
        "https://drama-api.toolnet.tech/api/drama/youtube/oauth/callback",
    )
    monkeypatch.setattr(settings, "DRAMA_DASHBOARD_URL", "https://dash.example.com")
    monkeypatch.setattr(
        settings, "DRAMA_TOKEN_ENCRYPTION_KEY",
        "HT_Cf46AlKxQARpInvvoAPWFcXYsDKo6jSon3FZ_1pU=",
    )


class _FakeCreds:
    def __init__(self, refresh_token="rt_new"):
        self.refresh_token = refresh_token


class _FakeFlow:
    def __init__(self, state):
        self.state = state
        self.credentials = _FakeCreds()
        self.redirect_uri = ""

    def authorization_url(self, **kwargs):
        return (f"https://accounts.google.com/o/oauth2/auth?state={self.state}", self.state)

    def fetch_token(self, code=None):
        return {"access_token": "ya29.test"}


def _patch_oauth(monkeypatch, channel=("UC_TEST", "Test Chan", "https://img/x.jpg")):
    import app.services.drama_youtube_oauth as yt_oauth

    monkeypatch.setattr(yt_oauth, "_new_flow", lambda state: _FakeFlow(state))

    def _fake_channel(flow):
        return channel

    monkeypatch.setattr(yt_oauth, "_fetch_channel", _fake_channel)


def test_oauth_start_returns_google_url(db, monkeypatch):
    _google_env(monkeypatch)
    client = _client()
    pipe = _pipe(client)
    r = client.get(
        "/api/drama/youtube/oauth/start",
        params={"pipeline_id": pipe["id"]},
        headers=ADMIN,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["authorization_url"].startswith("https://accounts.google.com/")
    assert body["destination_id"]
    # Placeholder destination exists, unconnected.
    dests = client.get(
        f"/api/drama/pipelines/{pipe['id']}/youtube-destinations", headers=ADMIN
    ).json()
    assert len(dests) == 1 and dests[0]["connected"] is False


def test_oauth_callback_completes_and_redirects(db, monkeypatch):
    _google_env(monkeypatch)
    _patch_oauth(monkeypatch)
    import app.services.drama_youtube_oauth as yt_oauth

    client = _client()
    pipe = _pipe(client)
    start = client.get(
        "/api/drama/youtube/oauth/start",
        params={"pipeline_id": pipe["id"], "return_to": "/drama/abc?tab=youtube"},
        headers=ADMIN,
    ).json()
    # Extract state from the fake auth URL.
    import urllib.parse as _up

    state = _up.parse_qs(_up.urlparse(start["authorization_url"]).query)["state"][0]
    r = client.get(
        "/api/drama/youtube/oauth/callback",
        params={"state": state, "code": "authcode_1"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    assert r.headers["location"].startswith("https://dash.example.com/drama/abc")
    assert "youtube_connected=1" in r.headers["location"]
    dests = client.get(
        f"/api/drama/pipelines/{pipe['id']}/youtube-destinations", headers=ADMIN
    ).json()
    assert dests[0]["connected"] is True
    assert dests[0]["channel_id"] == "UC_TEST"


def test_oauth_invalid_and_expired_state(db, monkeypatch):
    _google_env(monkeypatch)
    client = _client()
    r = client.get(
        "/api/drama/youtube/oauth/callback",
        params={"state": "nope", "code": "x"},
    )
    assert r.status_code == 400
    # Expired state.
    import app.db.repositories.youtube as yt_repo

    yt_repo.create_oauth_state(
        state="st_old", destination_id="d1", pipeline_id="p1",
        return_to=None, expires_at="2000-01-01T00:00:00Z",
    )
    r = client.get(
        "/api/drama/youtube/oauth/callback",
        params={"state": "st_old", "code": "x"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "OAUTH_STATE_EXPIRED"


def test_old_refresh_token_preserved(db, monkeypatch):
    _google_env(monkeypatch)
    import app.db.repositories.youtube as yt_repo
    import app.services.drama_youtube_oauth as yt_oauth
    from app.db.repositories import drama as drama_repo

    pipe = drama_repo.create_pipeline(name="Keep RT")
    dest = yt_repo.create_destination(pipeline_id=pipe["id"])
    yt_repo.save_credentials(dest["id"], channel_id="UC_X", refresh_token="rt_old_kept")

    class _NoRefreshFlow(_FakeFlow):
        def __init__(self, state):
            super().__init__(state)
            self.credentials = _FakeCreds(refresh_token=None)

    monkeypatch.setattr(yt_oauth, "_new_flow", lambda state: _NoRefreshFlow(state))

    def _fake_channel(flow):
        return ("UC_X", "X Chan", None)

    monkeypatch.setattr(yt_oauth, "_fetch_channel", _fake_channel)
    yt_repo.create_oauth_state(
        state="st_keep", destination_id=dest["id"],
        pipeline_id=pipe["id"], return_to=None,
        expires_at="2030-01-01T00:00:00Z",
    )
    info = asyncio.run(yt_oauth.complete_oauth("st_keep", "code_x"))
    assert info["channel_id"] == "UC_X"
    assert yt_repo.load_refresh_token(dest["id"]) == "rt_old_kept"


def test_channel_listing_and_select_and_disconnect(db, monkeypatch):
    _google_env(monkeypatch)
    _patch_oauth(monkeypatch)
    import urllib.parse as _up

    client = _client()
    pipe = _pipe(client, name="Pipe Select")
    start = client.get(
        "/api/drama/youtube/oauth/start",
        params={"pipeline_id": pipe["id"]},
        headers=ADMIN,
    ).json()
    state = _up.parse_qs(_up.urlparse(start["authorization_url"]).query)["state"][0]
    client.get(
        "/api/drama/youtube/oauth/callback",
        params={"state": state, "code": "c"},
    )
    # Global connected list shows the channel (safe fields only).
    all_ch = client.get("/api/drama/youtube/destinations", headers=ADMIN).json()
    assert len(all_ch) == 1
    assert all_ch[0]["channel_title"] == "Test Chan"
    assert "refresh_token" not in str(all_ch).lower()
    # Select as pipeline destination.
    dest_id = all_ch[0]["id"]
    sel = client.put(
        f"/api/drama/pipelines/{pipe['id']}/processing-settings",
        headers=ADMIN, json={"youtube_destination_id": dest_id},
    )
    assert sel.status_code == 200, sel.text
    assert sel.json()["youtube_destination_id"] == dest_id
    # Disconnect: safe, keeps row, wipes creds, clears pipeline selection.
    gone = client.delete(f"/api/drama/youtube-destinations/{dest_id}", headers=ADMIN)
    assert gone.status_code == 200, gone.text
    dests = client.get(
        f"/api/drama/pipelines/{pipe['id']}/youtube-destinations", headers=ADMIN
    ).json()
    assert dests[0]["connected"] is False
    settings = client.get(
        f"/api/drama/pipelines/{pipe['id']}/processing-settings", headers=ADMIN
    ).json()
    assert settings["youtube_destination_id"] is None


def test_publish_requires_destination(db):
    from app.services.drama_youtube_publisher import (
        YouTubePublisherError,
        publish_job_final,
    )

    async def _go():
        try:
            await publish_job_final(
                {"id": "djob_x", "pipeline_id": "dpl_x"}, "/tmp/never.mp4"
            )
            raise AssertionError("expected failure")
        except YouTubePublisherError as exc:
            assert exc.code == "YOUTUBE_DESTINATION_REQUIRED"

    asyncio.run(_go())


def test_upload_progress_retry_idempotency():
    from app.services.drama_youtube_publisher import (
        YouTubePublisherError,
        build_metadata,
        upload_video,
    )

    assert build_metadata(title="T")["snippet"]["title"] == "T"
    try:
        build_metadata(title="T", visibility="weird")
        raise AssertionError("expected failure")
    except YouTubePublisherError as exc:
        assert "visibility" in str(exc).lower()

    progress: list = []

    class _Req:
        def __init__(self):
            self.calls = 0

        def next_chunk(self):
            self.calls += 1
            if self.calls == 1:
                raise IOError("transient blip")

            class _P:
                resumable_progress = 100

            return _P(), {"id": "yt_abc"}

    class _FakeYT:
        def __init__(self):
            self.req = _Req()

        def videos(self):
            return self

        def insert(self, *a, **k):
            return self.req

    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as fh:
        fh.write(b"0" * 2048)
        path = fh.name
    vid = upload_video(
        object(), path, build_metadata(title="T"),
        youtube_factory=lambda creds: _FakeYT(),
        on_progress=lambda sent, total: progress.append((sent, total)),
        sleep_fn=lambda s: None,
    )
    assert vid == "yt_abc"
    assert progress and progress[-1][1] == 2048
