"""Per-pipeline processing modes: settings, chunking, orchestration, resume.

No network, no real uploads. ffmpeg is used only to mint tiny fixture
videos for the real concat path; all providers are injected fakes.
"""

import asyncio
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db.repositories import drama as repo
from app.db.repositories import processing as proc
from app.main import create_app
from app.services.processing import run_series_job, stage_plan

ADMIN = {"X-Admin-Token": "test_admin_token"}


def run(coro):
    return asyncio.run(coro)


def _client():
    return TestClient(create_app())


def _seed_series(db, n=3, prefix="proc"):
    p = repo.create_pipeline(name=f"{prefix} show")
    src = repo.create_source(pipeline_id=p["id"], external_series_id=f"{prefix}-b1")
    series, _ = repo.upsert_series(
        source_id=src["id"], provider="rapidix", external_series_id=f"{prefix}-b1"
    )
    for i in range(1, n + 1):
        repo.upsert_episode(
            series_id=series["id"], provider="rapidix",
            external_episode_id=f"{prefix}-e{i}", episode_number=i,
        )
    return p, series


def _fixture_mp4(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc=duration=1:size=160x90:rate=15",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True, timeout=120,
    )
    return path


# ---------- settings API ----------


def test_settings_defaults_direct_merge(db):
    c = _client()
    pid = c.post("/api/drama/pipelines", headers=ADMIN, json={"name": "S1"}).json()["id"]
    r = c.get(f"/api/drama/pipelines/{pid}/processing-settings", headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["processing_mode"] == "direct_merge"
    assert body["merge_all_episodes"] is True
    assert body["episodes_per_video"] is None


def test_settings_validation(db):
    c = _client()
    pid = c.post("/api/drama/pipelines", headers=ADMIN, json={"name": "S2"}).json()["id"]
    base = "/api/drama/pipelines/{pid}/processing-settings".format(pid=pid)
    bad_mode = c.put(base, headers=ADMIN, json={"processing_mode": "nope"})
    assert bad_mode.status_code == 400
    missing_epv = c.put(
        base, headers=ADMIN,
        json={"processing_mode": "dub_vi", "merge_all_episodes": False},
    )
    assert missing_epv.status_code == 400
    bad_epv = c.put(
        base, headers=ADMIN,
        json={"processing_mode": "dub_vi", "merge_all_episodes": False,
              "episodes_per_video": 0},
    )
    assert bad_epv.status_code == 400
    ok = c.put(
        base, headers=ADMIN,
        json={"processing_mode": "dub_vi", "merge_all_episodes": False,
              "episodes_per_video": 20, "target_language": "VI"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["episodes_per_video"] == 20
    assert ok.json()["target_language"] == "vi"


def test_plan_chunks_counts():
    assert proc.plan_chunks(60, {"merge_all_episodes": True, "episodes_per_video": None}) == [(1, 60)]
    assert proc.plan_chunks(60, {"merge_all_episodes": False, "episodes_per_video": 20}) == [
        (1, 20), (21, 40), (41, 60)]
    assert proc.plan_chunks(60, {"merge_all_episodes": False, "episodes_per_video": 10}) == [
        (1, 10), (11, 20), (21, 30), (31, 40), (41, 50), (51, 60)]
    assert proc.plan_chunks(0, {"merge_all_episodes": True}) == []


def test_stage_plan_skips():
    active, skipped = stage_plan("direct_merge")
    assert active == ["download", "merge", "upload", "cleanup"]
    assert "asr" in skipped and "translate" in skipped and "tts" in skipped
    active, skipped = stage_plan("translate_sub")
    assert "asr" in active and "translate" in active and "tts" in skipped
    active, _ = stage_plan("dub_vi")
    assert "tts" in active
    with pytest.raises(ValueError):
        stage_plan("nope")


def test_jobs_planned_from_settings(db):
    c = _client()
    _p, series = _seed_series(db, n=25, prefix="chunk")
    c.put(
        f"/api/drama/pipelines/{series['source_id'] and _pipeline_of(series)}"
        f"/processing-settings",
        headers=ADMIN,
        json={"processing_mode": "direct_merge", "merge_all_episodes": False,
              "episodes_per_video": 10},
    )
    r = c.post(f"/api/drama/series/{series['id']}/jobs", headers=ADMIN)
    assert r.status_code == 201, r.text
    items = r.json()["items"]
    assert len(items) == 3
    assert [(j["episode_start"], j["episode_end"]) for j in items] == [(1, 10), (11, 20), (21, 25)]


def _pipeline_of(series):
    from app.db.repositories import drama as _repo

    src = _repo.get_source(series["source_id"])
    assert src is not None
    return src["pipeline_id"]


# ---------- orchestrator ----------


def test_direct_merge_skips_asr_translation_tts(db, tmp_path):
    _p, series = _seed_series(db, n=2, prefix="dm")
    proc.update_settings(_pipeline_of(series), processing_mode="direct_merge")
    src = _fixture_mp4(tmp_path / "fix" / "ep.mp4")
    calls: list = []

    async def fake_download(ep, target):
        calls.append(("download", ep["episode_number"]))
        target.write_bytes(src.read_bytes())

    async def fake_upload(job, final_path):
        calls.append(("upload", final_path.name))
        assert final_path.exists()
        return {"youtube_video_id": "yt_1"}

    async def _boom(*a, **k):
        calls.append(("SHOULD_NOT_RUN",))
        raise AssertionError("must be skipped")

    job = proc.create_job(_pipeline_of(series), series["id"], "direct_merge", 0, 1, 2)
    out = run(run_series_job(
        job["id"], workdir=tmp_path / "work",
        download_episode=fake_download, run_asr=_boom,
        translate_text=_boom, synthesize_tts=_boom, upload_video=fake_upload,
    ))
    assert out["status"] == "completed", out
    assert out["skipped"] == ["asr", "translate", "tts", "render", "subtitle"]
    assert ("SHOULD_NOT_RUN",) not in calls
    assert sorted(c[1] for c in calls if c[0] == "download") == [1, 2]
    assert Path(out["output"]).exists()
    # episode source files cleaned, final kept
    assert not (tmp_path / "work" / job["id"] / "ep_001.mp4").exists()
    # merged output is ffprobe-readable
    from app.services.media.drama_media import probe_media

    assert probe_media(Path(out["output"]))["duration"] > 0


def test_translate_sub_invokes_asr_and_translation_not_tts(db, tmp_path):
    _p, series = _seed_series(db, n=1, prefix="ts")
    src = _fixture_mp4(tmp_path / "fix" / "ep.mp4")
    calls: list = []

    async def fake_download(ep, target):
        target.write_bytes(src.read_bytes())

    async def fake_asr(job, paths):
        calls.append("asr")
        return {"srt": "x"}

    async def fake_tr(job, asr_out):
        calls.append("translate")
        assert asr_out == {"srt": "x"}
        return {"srt_vi": "y"}

    async def fake_upload(job, final_path):
        calls.append("upload")
        return {}

    job = proc.create_job(_pipeline_of(series), series["id"], "translate_sub", 0, 1, 1)
    out = run(run_series_job(
        job["id"], workdir=tmp_path / "work", download_episode=fake_download,
        run_asr=fake_asr, translate_text=fake_tr, upload_video=fake_upload,
    ))
    assert out["status"] == "completed", out
    assert calls == ["asr", "translate", "upload"]
    assert out["translation"] == {"srt_vi": "y"}


def test_dub_vi_invokes_all_stages(db, tmp_path):
    _p, series = _seed_series(db, n=1, prefix="dub")
    src = _fixture_mp4(tmp_path / "fix" / "ep.mp4")
    calls: list = []

    async def fake_download(ep, target):
        target.write_bytes(src.read_bytes())

    async def fake_upload(job, final_path):
        return {}

    job = proc.create_job(_pipeline_of(series), series["id"], "dub_vi", 0, 1, 1)

    async def _asr(job, paths):
        calls.append("asr")

    async def _tr(job, asr_out):
        calls.append("translate")

    async def _tts(job, tr_out):
        calls.append("tts")

    out = run(run_series_job(
        job["id"], workdir=tmp_path / "work", download_episode=fake_download,
        run_asr=_asr, translate_text=_tr, synthesize_tts=_tts,
        upload_video=fake_upload,
    ))
    assert out["status"] == "completed", out
    assert calls == ["asr", "translate", "tts"]


def test_resume_skips_downloaded(db, tmp_path):
    _p, series = _seed_series(db, n=2, prefix="resume")
    src = _fixture_mp4(tmp_path / "fix" / "ep.mp4")
    job = proc.create_job(_pipeline_of(series), series["id"], "direct_merge", 0, 1, 2)
    # Simulate a previous partial run: ep1 file present + recorded.
    from app.db.repositories import drama as _repo

    ep1 = _repo.list_episodes(series["id"])[0][0]
    wdir = tmp_path / "work" / job["id"]
    wdir.mkdir(parents=True, exist_ok=True)
    (wdir / "ep_001.mp4").write_bytes(src.read_bytes())
    proc.mark_episode_downloaded(job["id"], ep1["id"])

    downloaded: list = []

    async def fake_download(ep, target):
        downloaded.append(ep["episode_number"])
        target.write_bytes(src.read_bytes())

    async def fake_upload(job, final_path):
        return {}

    out = run(run_series_job(
        job["id"], workdir=tmp_path / "work", download_episode=fake_download,
        upload_video=fake_upload,
    ))
    assert out["status"] == "completed", out
    assert downloaded == [2]


def test_episode_order_numeric(db, tmp_path):
    _p, series = _seed_series(db, n=12, prefix="ord")
    src = _fixture_mp4(tmp_path / "fix" / "ep.mp4")
    seen: list = []

    async def fake_download(ep, target):
        seen.append(ep["episode_number"])
        target.write_bytes(src.read_bytes())

    async def fake_upload(job, final_path):
        return {}

    job = proc.create_job(_pipeline_of(series), series["id"], "direct_merge", 0, 1, 12)
    out = run(run_series_job(
        job["id"], workdir=tmp_path / "work", download_episode=fake_download,
        upload_video=fake_upload,
    ))
    assert out["status"] == "completed", out
    assert seen == list(range(1, 13))
