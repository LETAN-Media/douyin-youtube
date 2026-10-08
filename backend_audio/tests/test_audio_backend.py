"""Audio backend: pipelines, sources, inventory, AI settings, scheduler, SRT, AI."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

ADMIN = {"X-Admin-Token": "test_admin_token"}


@pytest.fixture()
def client(db):
    return TestClient(create_app())


def test_pipelines_crud(db, client):
    r = client.post("/api/audio/pipelines", headers=ADMIN,
                    json={"name": "Ngon Tinh Audio"})
    assert r.status_code == 201
    pid = r.json()["id"]
    assert r.json()["pending_videos"] == 0
    r = client.get("/api/audio/pipelines", headers=ADMIN)
    assert len(r.json()["items"]) == 1
    r = client.put(f"/api/audio/pipelines/{pid}", headers=ADMIN,
                   json={"enabled": False})
    assert r.json()["enabled"] is False
    r = client.delete(f"/api/audio/pipelines/{pid}", headers=ADMIN)
    assert r.json()["deleted"] is True


def test_sources_multi_add_and_dedupe(db, client):
    pid = client.post("/api/audio/pipelines", headers=ADMIN,
                      json={"name": "P"}).json()["id"]
    urls = ("https://www.facebook.com/sourceA/reels/\n"
            "https://www.facebook.com/sourceB/reels/\n"
            "https://www.facebook.com/sourceA/reels/\n"
            "not-a-url")
    r = client.post(f"/api/audio/pipelines/{pid}/sources", headers=ADMIN,
                    json={"urls": urls})
    assert r.status_code == 201
    body = r.json()
    assert len(body["added"]) == 2
    assert len(body["existing"]) == 1
    assert len(body["invalid"]) == 1


def test_inventory_dedupe_and_reserve(db, client):
    from app.db.repositories import sources as src_repo

    pid = client.post("/api/audio/pipelines", headers=ADMIN,
                      json={"name": "P"}).json()["id"]
    first = None
    for i in range(2):
        r = client.post(f"/api/audio/pipelines/{pid}/inventory", headers=ADMIN,
                        json={"canonical_url": "https://www.facebook.com/reel/123",
                              "facebook_video_id": "123"})
        if i == 0:
            first = r.json()
    assert first["created"] is True
    assert r.json()["created"] is False
    item = src_repo.reserve_next_available(pid)
    assert item is not None and item["status"] == "reserved"
    assert src_repo.reserve_next_available(pid) is None


def test_ai_settings_version_and_reset(db, client):
    pid = client.post("/api/audio/pipelines", headers=ADMIN,
                      json={"name": "P"}).json()["id"]
    base = f"/api/audio/pipelines/{pid}/ai-settings"
    v1 = client.get(base, headers=ADMIN).json()["config_version"]
    r = client.put(base, headers=ADMIN,
                   json={"enabled": True, "language": "en",
                         "genre": "Horror Stories",
                         "expected_config_version": v1})
    assert r.status_code == 200
    assert r.json()["genre"] == "Horror Stories"
    r = client.put(base, headers=ADMIN,
                   json={"language": "zh", "expected_config_version": v1})
    assert r.status_code == 409
    r = client.post(base + "/reset", headers=ADMIN)
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_ai_isolation_between_pipelines(db, client):
    a = client.post("/api/audio/pipelines", headers=ADMIN,
                    json={"name": "A"}).json()["id"]
    b = client.post("/api/audio/pipelines", headers=ADMIN,
                    json={"name": "B"}).json()["id"]
    client.put(f"/api/audio/pipelines/{a}/ai-settings", headers=ADMIN,
               json={"system_prompt": "prompt A"})
    client.put(f"/api/audio/pipelines/{b}/ai-settings", headers=ADMIN,
               json={"system_prompt": "prompt B"})
    ra = client.get(f"/api/audio/pipelines/{a}/ai-settings",
                    headers=ADMIN).json()
    rb = client.get(f"/api/audio/pipelines/{b}/ai-settings",
                    headers=ADMIN).json()
    assert ra["system_prompt"] == "prompt A"
    assert rb["system_prompt"] == "prompt B"


def test_scheduler_tick_empty_queue(db, client):
    pid = client.post("/api/audio/pipelines", headers=ADMIN,
                      json={"name": "P"}).json()["id"]
    client.put(f"/api/audio/pipelines/{pid}/scheduler", headers=ADMIN,
               json={"enabled": True})
    r = client.post(f"/api/audio/pipelines/{pid}/scheduler/tick",
                    headers=ADMIN)
    # No connected destination -> not due
    assert r.json()["due"] is False


def test_srt_parse_format_merge():
    from app.services import subtitle_service as s

    text = ("1\n00:00:01,000 --> 00:00:02,000\nChao ban\n\n"
            "2\n00:00:02,500 --> 00:00:03,000\nTam biet\n")
    cues = s.parse_srt(text)
    assert len(cues) == 2 and cues[0][2] == "Chao ban"
    assert "00:00:01,000 --> 00:00:02,000" in s.format_srt(cues)
    plan = s.split_plan(1200, chunk_s=480, overlap_s=5)
    assert plan[0] == (0.0, 480.0) and plan[-1][1] == 1200


def test_ai_validation_and_templates():
    from app.services import ai_metadata as ai

    t, d, h = ai.validate_metadata(
        {"title": "x" * 150, "description": "d",
         "hashtags": ["#A", "#B", "#C"]})
    assert len(t) <= 100 and len(h) == 3
    with pytest.raises(ai.MetadataError):
        ai.validate_metadata({"title": "", "description": "d",
                              "hashtags": ["#A", "#B", "#C"]})
    assert ai.apply_title_template("{title} | Hay", "ABC") == "ABC | Hay"
    assert ai.normalize_language("EN") == "en"


def test_facebook_url_parsing():
    from app.services import facebook_urls as u

    assert u.is_facebook_url("https://www.facebook.com/foo/reels/")
    parsed = u.parse_facebook_source_url(
        "https://www.facebook.com/sourceA/reels/?q=1")
    assert parsed["canonical_url"] == "https://www.facebook.com/sourceA/reels"
    assert u.extract_facebook_video_id(
        "https://www.facebook.com/reel/1234567890123456/") == "1234567890123456"
    with pytest.raises(u.FacebookUrlError):
        u.parse_facebook_source_url("https://example.com/x")


def test_loop_render_short_clip(tmp_path):
    import subprocess

    from app.services import audio_extractor, loop_renderer

    bg = tmp_path / "bg.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "color=c=blue:s=320x240:d=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:d=2",
                    "-c:v", "libx264", "-c:a", "aac", "-shortest",
                    str(bg)], check=True, timeout=120)
    audio = tmp_path / "a.m4a"
    audio_extractor.extract_audio(bg, audio)
    dur = audio_extractor.probe_media(audio)["duration"]
    assert 1.5 < dur < 2.5
    out = tmp_path / "out.mp4"
    loop_renderer.build_loop_video(background=bg, audio=audio, output=out,
                                   duration=dur, threads=1)
    got = audio_extractor.probe_media(out)["duration"]
    assert abs(got - dur) < 1.0
