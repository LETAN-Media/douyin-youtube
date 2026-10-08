"""P0 regression tests: destinations, titles, hardsub, completion, readiness, reuse."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

ADMIN = {"X-Admin-Token": "test_admin_token"}


@pytest.fixture()
def client(db):
    return TestClient(create_app())


def _pipe(client, name="P"):
    return client.post("/api/audio/pipelines", headers=ADMIN,
                       json={"name": name}).json()["id"]


def _connect_dest(pid, channel="UC_TEST123", title="Kenh Test"):
    from app.db.repositories import audio as repo

    dest = repo.create_destination(pid)
    repo.update_destination(dest["id"], channel_id=channel,
                            channel_title=title)
    from app.db.client import get_client

    get_client().execute(
        "UPDATE audio_destinations SET connected = 1 WHERE id = ?",
        (dest["id"],))
    get_client().commit()
    return repo.get_destination(dest["id"])


# ---- P0-01 destination selection ----

def test_destination_explicit_wins_and_rejects_bad(db):
    from app.db.repositories import audio as repo

    pid = "p1"
    d1 = _connect_dest(pid, channel="UC_ONE")
    d2 = _connect_dest(pid, channel="UC_TWO")
    repo.upsert_scheduler_settings(pid, destination_id=d2["id"])
    assert repo.resolve_destination_for_job(pid)["id"] == d2["id"]
    # Disabled explicit destination -> None (never silently fall to another).
    repo.update_destination(d2["id"], enabled=False)
    assert repo.resolve_destination_for_job(pid) is None
    # Disconnected explicit destination -> None.
    from app.db.client import get_client

    get_client().execute("UPDATE audio_destinations SET connected = 0 WHERE id = ?",
                         (d2["id"],))
    get_client().commit()
    repo.upsert_scheduler_settings(pid, destination_id=d2["id"])
    assert repo.resolve_destination_for_job(pid) is None


def test_destination_fallback_and_empty(db):
    from app.db.repositories import audio as repo

    pid = "p2"
    assert repo.resolve_destination_for_job(pid) is None
    d = _connect_dest(pid)
    assert repo.resolve_destination_for_job(pid)["id"] == d["id"]


def test_publisher_import_path_has_no_missing_modules(db):
    import app.services.youtube_publisher as pub

    assert hasattr(pub, "publish_final")
    assert pub.DESTINATION_REQUIRED == "YOUTUBE_DESTINATION_REQUIRED"


# ---- P0-02 title precedence ----

def test_title_precedence_and_manual_preservation(db):
    from app.services.processing import resolve_initial_metadata

    job = {"ai_title": "Manual Title", "ai_description": "Manual desc",
           "ai_hashtags_json": json.dumps(["#A"]), "ai_metadata_status": "manual"}
    t, d, h = resolve_initial_metadata(job, {"title": "Resolver"}, {"caption": "Cap"})
    assert (t, d, h) == ("Manual Title", "Manual desc", ["#A"])

    t, d, h = resolve_initial_metadata({}, {"title": "Resolver Title"}, None)
    assert t == "Resolver Title" and d == "" and h == []

    t, _, _ = resolve_initial_metadata({}, {"title": "   "}, {"caption": "Inv Cap"})
    assert t == "Inv Cap"

    t, _, _ = resolve_initial_metadata({}, {"title": None}, {"caption": None})
    assert t == "Audio"

    t, _, _ = resolve_initial_metadata({}, {"title": {"nested": 1}}, None)
    assert t == "Audio"

    t, _, _ = resolve_initial_metadata({}, {"title": "x" * 200}, None)
    assert len(t) <= 100

    # Broken manual JSON never crashes; falls back to empty extras.
    job = {"ai_title": "T", "ai_hashtags_json": "not-json{{{"}
    t, d, h = resolve_initial_metadata(job, {"title": "R"}, None)
    assert t == "T" and h == []


# ---- P0-04 hardsub actually burns in ----

def _make_av(tmp_path, name="t"):
    import subprocess

    bg = tmp_path / f"{name}_bg.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "color=c=green:s=320x240:d=6",
                    "-f", "lavfi", "-i", "sine=frequency=440:d=6",
                    "-c:v", "libx264", "-c:a", "aac", "-shortest", str(bg)],
                   check=True, timeout=120)
    audio = tmp_path / f"{name}_a.m4a"
    from app.services import audio_extractor

    audio_extractor.extract_audio(bg, audio)
    srt = tmp_path / f"{name}.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:05,000\nChào bạn tiếng Việt ơi\n",
                   encoding="utf-8")
    logo = tmp_path / f"{name}_logo.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "color=c=red:s=40x40:d=1",
                    "-frames:v", "1", str(logo)], check=True, timeout=60)
    return bg, audio, srt, logo


def _frame_hash(path, at_s):
    import subprocess

    import hashlib

    out = path.parent / f"frame_{at_s}.raw"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(at_s),
                    "-i", str(path), "-frames:v", "1",
                    "-f", "rawvideo", "-pix_fmt", "rgb24", str(out)],
                   check=True, timeout=60)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    out.unlink(missing_ok=True)
    return digest


def test_hardsub_visible_logo_audio_duration(tmp_path):
    from app.services import audio_extractor, loop_renderer

    bg, audio, srt, logo = _make_av(tmp_path)
    dur = audio_extractor.probe_media(audio)["duration"]
    plain = tmp_path / "plain.mp4"
    loop_renderer.build_loop_video(background=bg, audio=audio, output=plain,
                                   duration=dur, logo=logo, threads=1)
    burned = tmp_path / "burned.mp4"
    loop_renderer.build_loop_video(background=bg, audio=audio, output=burned,
                                   duration=dur, logo=logo, threads=1,
                                   srt=srt, hardsub=True)
    info = audio_extractor.probe_media(burned)
    assert abs(info["duration"] - dur) < 1.0
    assert info.get("audio_codec") is not None
    # Same green background: burned frame during the cue MUST differ.
    assert _frame_hash(burned, 2) != _frame_hash(plain, 2)
    # Missing SRT with hardsub=True is an explicit error, not silent no-sub.
    import pytest as _pytest

    with _pytest.raises(loop_renderer.RenderError):
        loop_renderer.build_loop_video(background=bg, audio=audio,
                                       output=tmp_path / "x.mp4",
                                       duration=dur, threads=1, hardsub=True)


# ---- P0-05 completion never regresses ----

def test_completed_job_keeps_state(db, client):
    from app.db.repositories import jobs as jobs_repo

    pid = _pipe(client)
    job = jobs_repo.create_job(pid, mode="manual")
    jobs_repo.update_job(job["id"], status="completed", stage="completed:done",
                         progress_percent=100, youtube_video_id="UC_VID")
    assert jobs_repo.recover_stale_running() == 0
    fresh = jobs_repo.get_job(job["id"])
    assert fresh["status"] == "completed" and fresh["progress_percent"] == 100
    assert jobs_repo.claim_next_queued("w1") is None


# ---- P0-06 readiness ----

def test_ready_fails_without_production_db(tmp_path, monkeypatch):
    from app.config import settings
    from app.db import client as dbc

    saved = (settings.AUDIO_ADMIN_TOKEN, settings.APP_ENV,
             settings.AUDIO_TURSO_URL, settings.AUDIO_DB_PATH)
    f = tmp_path / "nodb.sqlite3"
    monkeypatch.setenv("AUDIO_ADMIN_TOKEN", "t")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("AUDIO_TURSO_URL", raising=False)
    settings.AUDIO_ADMIN_TOKEN = "t"
    settings.APP_ENV = "production"
    settings.AUDIO_TURSO_URL = ""
    settings.AUDIO_DB_PATH = str(f)
    dbc.reset_client()
    try:
        c = TestClient(create_app(), raise_server_exceptions=False)
        assert c.get("/health").status_code == 200
        r = c.get("/ready")
        assert r.status_code == 503
        assert "ready" in r.json() and r.json()["ready"] is False
    finally:
        (settings.AUDIO_ADMIN_TOKEN, settings.APP_ENV,
         settings.AUDIO_TURSO_URL, settings.AUDIO_DB_PATH) = saved
        dbc.reset_client()


# ---- P0-07 video id reuse, captions retry independently ----

def test_published_job_never_reuploads(db, client, monkeypatch):
    import app.services.youtube_publisher as pub
    from app.db.repositories import jobs as jobs_repo
    from app.services import youtube_oauth as oauth
    from cryptography.fernet import Fernet

    from app.config import settings

    monkeypatch.setattr(settings, "AUDIO_TOKEN_ENCRYPTION_KEY",
                        Fernet.generate_key().decode())

    pid = _pipe(client)
    dest = _connect_dest(pid)
    oauth.save_credentials(dest["id"], "UC_TEST123", "refresh-x")
    job = jobs_repo.create_job(pid, mode="manual")
    jobs_repo.update_job(job["id"], status="running",
                         youtube_video_id="UC_EXISTING")

    async def _boom(*a, **k):
        raise AssertionError("must not re-upload")

    async def fake_caption(refresh_token, video_id, srt_path, language="vi"):
        assert video_id == "UC_EXISTING"
        assert srt_path.exists()
        return None

    monkeypatch.setattr(pub, "_blocking_upload", _boom)
    monkeypatch.setattr(pub, "_blocking_caption_upload", fake_caption)
    monkeypatch.setattr(pub.asyncio, "to_thread",
                        _fake_to_thread(fake_caption), raising=False)

    import asyncio
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        srt = Path(tmp) / "s.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHi\n")
        out = asyncio.run(pub.publish_final(
            job=jobs_repo.get_job(job["id"]), video_path=Path(tmp) / "v.mp4",
            title="T", srt_path=srt, captions_required=True))
    assert out == {"youtube_video_id": "UC_EXISTING", "already": True,
                   "captions": "uploaded"}


def _fake_to_thread(fake_caption):
    async def _to_thread(func, *args, **kwargs):
        if func.__name__ == "_blocking_caption_upload":
            return await fake_caption(*args, **kwargs)
        return func(*args, **kwargs)

    return _to_thread


def test_oauth_credentials_roundtrip_compatible(db, monkeypatch):
    from cryptography.fernet import Fernet

    from app.config import settings
    from app.services import youtube_oauth as oauth

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("AUDIO_TOKEN_ENCRYPTION_KEY", key)
    settings.AUDIO_TOKEN_ENCRYPTION_KEY = key
    oauth.save_credentials("aud_x", "UC_CHAN", "refresh-123")
    creds = oauth.load_credentials("aud_x")
    assert creds == {"refresh_token": "refresh-123", "channel_id": "UC_CHAN"}
