"""Tests for Audio Truyện using Template as background video on R2."""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

ADMIN = {"X-Admin-Token": "test_admin_token"}


@pytest.fixture(autouse=True)
def mock_r2_exists(monkeypatch):
    from app.services import r2_storage

    monkeypatch.setattr(r2_storage, "object_exists",
                        lambda k: bool(k and not str(k).startswith("missing_")))


@pytest.fixture()
def client(db):
    return TestClient(create_app())


def _setup_pipeline(client, name="Audio Truyện", p_type="auto"):
    pid = client.post("/api/audio/pipelines", headers=ADMIN,
                      json={"name": name, "pipeline_type": p_type}).json()["id"]
    return pid


def _add_dest(pid):
    from app.db.client import get_client
    from app.db.repositories import new_id, now_iso

    did = new_id("aud")
    client = get_client()
    client.execute(
        "INSERT INTO audio_destinations (id, pipeline_id, channel_id, channel_title, "
        "connected, enabled, created_at, updated_at) "
        "VALUES (?, ?, 'UC_TEST', 'Test Channel', 1, 1, ?, ?)",
        (did, pid, now_iso(), now_iso()))
    client.commit()
    return did


def _add_template(pid, enabled=1, object_key=None, filename="template.mov"):
    from app.db.client import get_client
    from app.db.repositories import new_id, now_iso

    aid = new_id("amedia")
    key = object_key or f"audio/pipelines/{pid}/templates/{aid}.MOV"
    client = get_client()
    client.execute(
        "INSERT INTO audio_media_assets (id, pipeline_id, kind, object_key, file_name, "
        "mime, width, height, duration_seconds, bytes, enabled, created_at, updated_at) "
        "VALUES (?, ?, 'template', ?, ?, 'video/quicktime', 1920, 1080, 7.24, 2976687, ?, ?, ?)",
        (aid, pid, key, filename, enabled, now_iso(), now_iso()))
    client.commit()
    return aid


def test_audio_truyen_uses_template_as_background(db, client):
    """Audio Truyện with only template assets enabled should be due and pick template as background."""
    from app.db.repositories import audio as audio_repo
    from app.db.repositories import sources as src_repo
    from app.services import scheduler

    pid = _setup_pipeline(client, name="Audio Truyện")
    _add_dest(pid)
    tid = _add_template(pid, enabled=1)
    audio_repo.upsert_scheduler_settings(pid, enabled=True, max_videos_per_day=3)
    src_repo.upsert_inventory_item(pid, None, "fb_vid_1", "https://facebook.com/reel/1/")

    # Background source for Audio Truyện should resolve to 'template'
    assert audio_repo.get_background_source(pid) == "template"

    available = audio_repo.get_available_background_assets(pid)
    assert len(available) == 1
    assert available[0]["id"] == tid
    assert available[0]["kind"] == "template"

    picked = audio_repo.pick_background_asset(pid)
    assert picked is not None
    assert picked["id"] == tid

    due, reason = scheduler.pipeline_due(pid)
    assert due is True
    assert reason == "due"


def test_missing_r2_object_blocks_scheduler(db, client):
    """If template object is missing from R2, scheduler blocks with BACKGROUND_R2_OBJECT_MISSING."""
    from app.db.repositories import audio as audio_repo
    from app.db.repositories import sources as src_repo
    from app.services import scheduler

    pid = _setup_pipeline(client, name="Audio Truyện")
    _add_dest(pid)
    # Add template with missing object key prefix
    _add_template(pid, enabled=1, object_key="missing_template.mov")
    audio_repo.upsert_scheduler_settings(pid, enabled=True, max_videos_per_day=3)
    src_repo.upsert_inventory_item(pid, None, "fb_vid_1", "https://facebook.com/reel/1/")

    due, reason = scheduler.pipeline_due(pid)
    assert due is False
    assert reason == "BACKGROUND_R2_OBJECT_MISSING"


def test_other_pipeline_defaults_to_background_kind(db, client):
    """Pipelines other than Audio Truyện default to kind='background'."""
    from app.db.repositories import audio as audio_repo
    from app.services import scheduler

    pid = _setup_pipeline(client, name="Other Pipeline")
    _add_dest(pid)
    _add_template(pid, enabled=1)
    audio_repo.upsert_scheduler_settings(pid, enabled=True, max_videos_per_day=3)

    # Defaults to 'background'
    assert audio_repo.get_background_source(pid) == "background"

    # Since other pipeline has 0 background assets, scheduler blocks with NO_BACKGROUND
    due, reason = scheduler.pipeline_due(pid)
    assert due is False
    assert reason == "NO_BACKGROUND"


def test_explicit_background_source_setting(db, client):
    """Pipeline can explicitly configure background_source='template' via settings."""
    from app.db.repositories import audio as audio_repo
    from app.db.repositories import sources as src_repo
    from app.services import scheduler

    pid = _setup_pipeline(client, name="Custom Pipeline")
    _add_dest(pid)
    tid = _add_template(pid, enabled=1)
    audio_repo.upsert_scheduler_settings(pid, enabled=True, max_videos_per_day=3)
    src_repo.upsert_inventory_item(pid, None, "fb_vid_1", "https://facebook.com/reel/1/")

    # Initially blocked
    due, reason = scheduler.pipeline_due(pid)
    assert due is False
    assert reason == "NO_BACKGROUND"

    # Update settings to background_source='template'
    res = client.put(f"/api/audio/pipelines/{pid}/processing-settings",
                     headers=ADMIN, json={"background_source": "template"})
    assert res.status_code == 200
    assert res.json()["background_source"] == "template"

    # Now due is True!
    due, reason = scheduler.pipeline_due(pid)
    assert due is True
    assert reason == "due"


def test_same_template_not_applied_twice_as_overlay(db, client):
    """Requirement 6: If the template is used as background, it must NOT be applied as 600s periodic overlay."""
    from app.db.repositories import audio as audio_repo

    pid = _setup_pipeline(client, name="Audio Truyện")
    tid = _add_template(pid, enabled=1)

    # Pick background asset
    bg_asset = audio_repo.pick_background_asset(pid)
    assert bg_asset["id"] == tid

    # When picking template overlay with avoid_asset_id=bg_asset['id'], it returns None
    overlay = audio_repo.pick_random_template(pid, avoid_asset_id=bg_asset["id"])
    assert overlay is None


def test_processing_settings_validation(db, client):
    """Validates that background_source only accepts 'background' or 'template'."""
    pid = _setup_pipeline(client, name="Audio Truyện")
    res = client.put(f"/api/audio/pipelines/{pid}/processing-settings",
                     headers=ADMIN, json={"background_source": "invalid_source"})
    assert res.status_code == 400
    assert res.json()["error"] == "BAD_BACKGROUND_SOURCE"


def test_render_loop_video_with_mov_template(tmp_path):
    """Tests that loop_renderer.build_loop_video loops a short video (MOV) to full audio duration."""
    from app.services import loop_renderer

    bg_mov = tmp_path / "bg.mov"
    audio_m4a = tmp_path / "audio.m4a"
    out_mp4 = tmp_path / "output.mp4"

    # Generate a 2-second dummy video (simulating short template)
    subprocess.run([
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=1280x720:rate=24",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(bg_mov)
    ], check=True)

    # Generate a 6-second dummy audio
    subprocess.run([
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=6",
        "-c:a", "aac", "-b:a", "128k", str(audio_m4a)
    ], check=True)

    # Render looped video for 6 seconds
    loop_renderer.build_loop_video(
        background=bg_mov,
        audio=audio_m4a,
        output=out_mp4,
        duration=6.0,
        threads=2
    )

    assert out_mp4.exists()
    assert out_mp4.stat().st_size > 0

    # Probe duration with ffprobe
    res = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(out_mp4)
    ], capture_output=True, text=True, check=True)
    rendered_dur = float(res.stdout.strip())
    assert 5.8 <= rendered_dur <= 6.2
