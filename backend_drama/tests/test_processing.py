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
    assert active == ["download", "render", "merge", "upload", "cleanup"]
    assert "asr" in skipped and "translate" in skipped and "tts" in skipped
    assert "render" in active
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
        # Final must be ffprobe-readable at upload time.
        from app.services.media.drama_media import probe_media

        assert probe_media(final_path)["duration"] > 0
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
    assert out["skipped"] == ["asr", "translate", "tts", "subtitle"]
    assert ("SHOULD_NOT_RUN",) not in calls
    assert sorted(c[1] for c in calls if c[0] == "download") == [1, 2]
    # After successful upload everything local is cleaned, including final.
    assert not Path(out["output"]).exists()
    assert not (tmp_path / "work" / job["id"] / "ep_001.mp4").exists()
    assert not (tmp_path / "work" / job["id"] / "merged.mp4").exists()


def test_translate_sub_invokes_asr_and_translation_not_tts(db, tmp_path):
    _p, series = _seed_series(db, n=1, prefix="ts")
    src = _fixture_mp4(tmp_path / "fix" / "ep.mp4")
    calls: list = []

    async def fake_download(ep, target):
        target.write_bytes(src.read_bytes())

    async def fake_asr(job, ep, src):
        calls.append(("asr", ep["episode_number"]))
        return {"srt": "x"}

    async def fake_tr(job, ep, asr_out):
        calls.append(("translate", ep["episode_number"]))
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
    assert calls == [("asr", 1), ("translate", 1), "upload"]


def test_dub_vi_invokes_all_stages(db, tmp_path):
    _p, series = _seed_series(db, n=1, prefix="dub")
    src = _fixture_mp4(tmp_path / "fix" / "ep.mp4")
    calls: list = []

    async def fake_download(ep, target):
        target.write_bytes(src.read_bytes())

    async def fake_upload(job, final_path):
        return {}

    job = proc.create_job(_pipeline_of(series), series["id"], "dub_vi", 0, 1, 1)

    async def _asr(job, ep, src):
        calls.append("asr")

    async def _tr(job, ep, asr_out):
        calls.append("translate")

    async def _tts(job, ep, tr_out):
        calls.append("tts")

    out = run(run_series_job(
        job["id"], workdir=tmp_path / "work", download_episode=fake_download,
        run_asr=_asr, translate_text=_tr, synthesize_tts=_tts,
        upload_video=fake_upload,
    ))
    assert out["status"] == "completed", out
    assert calls == ["asr", "translate", "tts"]


def test_resume_skips_downloaded(db, tmp_path):
    from app.db.repositories import episode_tasks as tasks_repo

    _p, series = _seed_series(db, n=2, prefix="resume")
    src = _fixture_mp4(tmp_path / "fix" / "ep.mp4")
    job = proc.create_job(_pipeline_of(series), series["id"], "direct_merge", 0, 1, 2)
    # Simulate a previous partial run: ep1 rendered (segment present).
    from app.db.repositories import drama as _repo

    ep1 = _repo.list_episodes(series["id"])[0][0]
    tasks_repo.ensure_tasks(job["id"], _repo.list_episodes(series["id"])[0])
    wdir = tmp_path / "work" / job["id"]
    (wdir / "segments").mkdir(parents=True, exist_ok=True)
    (wdir / "segments" / "segment_001.mp4").write_bytes(src.read_bytes())
    tasks_repo.mark_status(job["id"], ep1["id"], "rendered",
                           segment_path=str(wdir / "segments" / "segment_001.mp4"),
                           segment_bytes=100, duration=1.0)

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


# ---------- templates ----------


def test_template_crud_and_settings_link(db):
    from fastapi.testclient import TestClient

    from app.db.repositories import templates as templates_repo
    from app.main import create_app

    client = TestClient(create_app())
    bad = client.post(
        "/api/drama/templates", headers=ADMIN,
        json={"name": "X", "asset_url": "not-a-url"},
    )
    assert bad.status_code == 400
    tpl = templates_repo.create_template(
        name="Frame A", asset_url="file:///tmp/frame_a.png",
        canvas_width=1280, canvas_height=720,
        content_x=0, content_y=0, content_width=1280, content_height=720,
    )
    assert tpl["id"].startswith("dtpl_")
    assert [t["id"] for t in templates_repo.list_templates()] == [tpl["id"]]

    p = repo.create_pipeline(name="Tpl Pipe")
    r = client.put(
        f"/api/drama/pipelines/{p['id']}/processing-settings", headers=ADMIN,
        json={"template_enabled": True, "template_id": tpl["id"],
              "template_mode": "overlay", "youtube_destination_id": "ytd_1",
              "auto_publish": False},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["template_enabled"] is True
    assert body["template_id"] == tpl["id"]
    assert body["youtube_destination_id"] == "ytd_1"
    assert body["auto_publish"] is False
    missing = client.put(
        f"/api/drama/pipelines/{p['id']}/processing-settings", headers=ADMIN,
        json={"template_id": "dtpl_nope"},
    )
    assert missing.status_code == 404
    assert templates_repo.delete_template(tpl["id"]) is True
    assert templates_repo.delete_template(tpl["id"]) is False


def _make_frame(path):
    import subprocess

    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", "color=c=0x1a1a2e:size=1280x720:duration=1",
         "-frames:v", "1", str(path)],
        check=True, timeout=60,
    )
    return path


def test_template_render_once_over_merged(db, tmp_path):
    from app.services.render.template_renderer import render_template

    _p, series = _seed_series(db, n=2, prefix="tmpl")
    src = _fixture_mp4(tmp_path / "fix" / "ep.mp4")
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    from app.services.merge import concat_paths

    ep_paths = []
    for i in (1, 2):
        target = work / f"ep_{i:03d}.mp4"
        target.write_bytes(src.read_bytes())
        ep_paths.append(target)
    merged = work / "merged.mp4"
    concat_paths(ep_paths, merged)
    frame = _make_frame(work / "frame.png")
    tpl = {
        "id": "dtpl_t", "asset_url": f"file://{frame}",
        "canvas_width": 1280, "canvas_height": 720,
        "content_x": 0, "content_y": 0,
        "content_width": 1280, "content_height": 720,
    }
    final = work / "final.mp4"
    render_template(merged, tpl, final, workdir=work)
    from app.services.media.drama_media import probe_media

    probe = probe_media(final)
    assert probe["duration"] > 0
    assert probe["width"] == 1280 and probe["height"] == 720
    plain = work / "plain.mp4"
    render_template(merged, None, plain, workdir=work)
    assert plain.exists()


def test_template_missing_asset_fails_loudly(db, tmp_path):
    from app.services.render.template_renderer import TemplateError, render_template

    _p, series = _seed_series(db, n=1, prefix="tmplmiss")
    src = _fixture_mp4(tmp_path / "fix" / "ep.mp4")
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    (work / "merged.mp4").write_bytes(src.read_bytes())
    with pytest.raises(TemplateError) as exc:
        render_template(
            work / "merged.mp4",
            {"id": "x", "asset_url": "file:///nope/missing.png"},
            work / "final.mp4", workdir=work,
        )
    assert exc.value.code == "TEMPLATE_MISSING"


def test_disk_guard_blocks_when_full(db, tmp_path, monkeypatch):
    from app.services.render import disk as disk_mod

    _p, series = _seed_series(db, n=1, prefix="disk")
    monkeypatch.setattr(disk_mod, "disk_free_bytes", lambda path: 1024)
    job = proc.create_job(_pipeline_of(series), series["id"], "direct_merge", 0, 1, 1)

    async def _boom(ep, target):
        raise AssertionError("must not download without disk space")

    async def _upload(job, final_path):
        return {}

    out = run(run_series_job(
        job["id"], workdir=tmp_path / "work", download_episode=_boom,
        upload_video=_upload,
    ))
    assert out["status"] == "failed", out
    assert out["error"]["code"] == "INSUFFICIENT_TEMP_STORAGE"


def test_disk_estimate_scales_with_episodes():
    from app.services.render import disk as disk_mod

    small = disk_mod.estimate_job_bytes([{"duration": 600}])
    big = disk_mod.estimate_job_bytes([{"duration": 600}] * 60)
    assert big == small * 60
    assert small > 0


def test_upload_idempotency_skips_duplicate(db, tmp_path):
    _p, series = _seed_series(db, n=1, prefix="idem")
    job = proc.create_job(_pipeline_of(series), series["id"], "direct_merge", 0, 1, 1)
    proc.update_job(job["id"], status="completed", youtube_video_id="yt_done",
                    output_path="/tmp/gone.mp4")

    async def _boom(*a, **k):
        raise AssertionError("must not run anything when already published")

    out = run(run_series_job(
        job["id"], workdir=tmp_path / "work", download_episode=_boom,
        upload_video=_boom,
    ))
    assert out["status"] == "completed"
    assert out["youtube_video_id"] == "yt_done"


def test_orchestrator_template_stage_end_to_end(db, tmp_path):
    _p, series = _seed_series(db, n=2, prefix="e2e")
    src = _fixture_mp4(tmp_path / "fix" / "ep.mp4")
    frame = _make_frame(tmp_path / "fix" / "frame.png")
    from app.db.repositories import templates as templates_repo

    tpl = templates_repo.create_template(
        name="T", asset_url=f"file://{frame}",
        canvas_width=1280, canvas_height=720,
        content_x=0, content_y=0, content_width=1280, content_height=720,
    )
    proc.update_settings(
        _pipeline_of(series), processing_mode="direct_merge",
        template_enabled=True, template_id=tpl["id"],
    )
    seen_final = {}

    async def fake_download(ep, target):
        target.write_bytes(src.read_bytes())

    async def fake_upload(job, final_path):
        seen_final["path"] = str(final_path)
        from app.services.media.drama_media import probe_media

        assert probe_media(final_path)["width"] == 1280
        return {"youtube_video_id": "yt_t"}

    job = proc.create_job(_pipeline_of(series), series["id"], "direct_merge", 0, 1, 2)
    out = run(run_series_job(
        job["id"], workdir=tmp_path / "work", download_episode=fake_download,
        upload_video=fake_upload,
    ))
    assert out["status"] == "completed", out
    assert out["stages"]["render"]["state"] == "done"
    assert seen_final["path"].endswith("final.mp4")


# ---------- SVG-first templates ----------

VALID_SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="720" height="1280" viewBox="0 0 720 1280">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#141428"/>
      <stop offset="1" stop-color="#1e1e3f"/>
    </linearGradient>
    <clipPath id="c"><rect x="90" y="160" width="540" height="960"/></clipPath>
  </defs>
  <path d="M0,0 H720 V1280 H0 Z M90,160 h540 v960 h-540 Z" fill="url(#g)" fill-rule="evenodd"/>
  <text x="360" y="1170" text-anchor="middle" font-size="20" fill="#fff">Hi</text>
</svg>
"""


def _write_svg(tmp_path, name="t.svg", content=VALID_SVG):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_svg_validation_accepts_good(tmp_path):
    from app.services.render.template_renderer import validate_svg

    dims = validate_svg(VALID_SVG.encode())
    assert dims["viewBox"] == "0 0 720 1280"


def test_svg_validation_rejects_bad():
    from app.services.render.template_renderer import TemplateError, validate_svg

    cases = [
        (b"not xml at all", "TEMPLATE_INVALID_SVG"),
        (b"<html><body>hi</body></html>", "TEMPLATE_INVALID_SVG"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>', "TEMPLATE_INVALID_SVG"),
        (b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><script>alert(1)</script></svg>', "TEMPLATE_UNSAFE_SVG"),
        (b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><a href="javascript:alert(1)"><rect/></a></svg>', "TEMPLATE_UNSAFE_SVG"),
        (b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><image href="https://evil.example.com/x.png"/></svg>', "TEMPLATE_UNSAFE_SVG"),
    ]
    for bad, code in cases:
        with pytest.raises(TemplateError) as exc:
            validate_svg(bad)
        assert exc.value.code == code, bad[:40]


def test_svg_rasterize_exact_canvas(tmp_path):
    from app.services.media.drama_media import probe_media
    from app.services.render.template_renderer import rasterize_svg

    src = _write_svg(tmp_path)
    out = tmp_path / "frame.png"
    rasterize_svg(src, out, width=720, height=1280)
    assert out.exists() and out.stat().st_size > 0
    probe = probe_media(out)
    assert probe["width"] == 720 and probe["height"] == 1280


def test_svg_transparency_preserved(tmp_path):
    import subprocess

    from app.services.render.template_renderer import rasterize_svg

    src = _write_svg(tmp_path)
    out = tmp_path / "frame.png"
    rasterize_svg(src, out, width=720, height=1280)
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(out), "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
        capture_output=True, check=True, timeout=60,
    ).stdout
    W, H = 720, 1280

    def alpha(x, y):
        return raw[(y * W + x) * 4 + 3]

    import statistics

    content = [alpha(x, y) for x in range(100, 620, 40) for y in range(170, 1110, 40)]
    assert statistics.mean(content) < 30, "content window must stay transparent"


def test_svg_vertical_and_landscape_sizes(tmp_path):
    from app.services.render.template_renderer import rasterize_svg

    src = _write_svg(tmp_path)
    for w, h in [(720, 1280), (1080, 1920), (1920, 1080)]:
        out = tmp_path / f"f_{w}x{h}.png"
        rasterize_svg(src, out, width=w, height=h)
        assert out.stat().st_size > 0


def test_svg_fetch_preserves_extension(tmp_path):
    from app.services.render.template_renderer import fetch_template_asset

    src = _write_svg(tmp_path, "real.svg")
    dest = fetch_template_asset(f"file://{src}", tmp_path / "tpl_dl")
    assert dest.suffix == ".svg"
    assert dest.read_bytes() == src.read_bytes()


def test_svg_rasterize_missing_rsvg(tmp_path, monkeypatch):
    import subprocess

    from app.services.render import template_renderer as tr

    src = _write_svg(tmp_path)

    def _boom(*a, **k):
        raise FileNotFoundError("no rsvg")

    monkeypatch.setattr(subprocess, "run", _boom)
    with pytest.raises(tr.TemplateError) as exc:
        tr.rasterize_svg(src, tmp_path / "x.png", width=720, height=1280)
    assert exc.value.code == "TEMPLATE_RENDER_FAILED"


def test_svg_temp_files_cleaned(db, tmp_path):
    from app.services.render.template_renderer import render_template

    _p, series = _seed_series(db, n=1, prefix="svgclean")
    src = _fixture_mp4(tmp_path / "fix" / "ep.mp4")
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    (work / "merged.mp4").write_bytes(src.read_bytes())
    svg = _write_svg(tmp_path, "frame.svg")
    tpl = {
        "id": "dtpl_svg", "asset_url": f"file://{svg}",
        "canvas_width": 720, "canvas_height": 1280,
        "content_x": 90, "content_y": 160,
        "content_width": 540, "content_height": 960,
    }
    out = render_template(work / "merged.mp4", tpl, work / "final.mp4", workdir=work)
    assert out.exists()
    leftovers = [p.name for p in work.iterdir()
                 if p.suffix == ".svg" or p.name in ("template_frame.png", "template_source.svg")]
    assert leftovers == [], leftovers


# ---------- per-episode architecture ----------


def test_episode_tasks_created_and_skip_rendered(db, tmp_path):
    from app.db.repositories import episode_tasks as tasks_repo

    _p, series = _seed_series(db, n=2, prefix="tasks")
    job = proc.create_job(_pipeline_of(series), series["id"], "direct_merge", 0, 1, 2)
    assert tasks_repo.list_tasks(job["id"]) == []
    src = _fixture_mp4(tmp_path / "fix" / "ep.mp4")

    async def fake_download(ep, target):
        target.write_bytes(src.read_bytes())

    async def fake_upload(job, final_path):
        return {"youtube_video_id": "yt_x"}

    out = run(run_series_job(
        job["id"], workdir=tmp_path / "work", download_episode=fake_download,
        upload_video=fake_upload,
    ))
    assert out["status"] == "completed", out
    tasks = tasks_repo.list_tasks(job["id"])
    assert [t["episode_number"] for t in tasks] == [1, 2]
    assert all(t["status"] == "rendered" for t in tasks)
    assert tasks_repo.count_by_status(job["id"]) == {"rendered": 2}
    assert [e["n"] for e in out["episodes"]] == [1, 2]


def test_failed_episode_isolated_and_retry_single(db, tmp_path):
    from app.db.repositories import episode_tasks as tasks_repo

    _p, series = _seed_series(db, n=3, prefix="failiso")
    src = _fixture_mp4(tmp_path / "fix" / "ep.mp4")
    job = proc.create_job(_pipeline_of(series), series["id"], "direct_merge", 0, 1, 3)

    async def flaky_download(ep, target):
        if ep["episode_number"] == 2:
            raise RuntimeError("network blip")
        target.write_bytes(src.read_bytes())

    async def fake_upload(job, final_path):
        return {"youtube_video_id": "yt_x"}

    out = run(run_series_job(
        job["id"], workdir=tmp_path / "work", download_episode=flaky_download,
        upload_video=fake_upload,
    ))
    assert out["status"] == "failed", out
    assert out["error"]["code"] == "DOWNLOAD_FAILED"
    counts = tasks_repo.count_by_status(job["id"])
    assert counts.get("failed", 0) == 1
    ep2 = [t for t in tasks_repo.list_tasks(job["id"]) if t["episode_number"] == 2][0]
    assert ep2["status"] == "failed"
    reset = tasks_repo.reset_tasks(job["id"], [ep2["episode_id"]])
    assert reset == 1

    async def good_download(ep, target):
        target.write_bytes(src.read_bytes())

    out2 = run(run_series_job(
        job["id"], workdir=tmp_path / "work", download_episode=good_download,
        upload_video=fake_upload,
    ))
    assert out2["status"] == "completed", out2
    assert tasks_repo.count_by_status(job["id"]).get("rendered", 0) == 3


def test_retry_all_failed(db, tmp_path):
    from app.db.repositories import episode_tasks as tasks_repo

    _p, series = _seed_series(db, n=2, prefix="retryall")
    src = _fixture_mp4(tmp_path / "fix" / "ep.mp4")
    job = proc.create_job(_pipeline_of(series), series["id"], "direct_merge", 0, 1, 2)

    async def always_fail(ep, target):
        raise RuntimeError("down")

    async def fake_upload(job, final_path):
        return {}

    out = run(run_series_job(
        job["id"], workdir=tmp_path / "work", download_episode=always_fail,
        upload_video=fake_upload,
    ))
    assert out["status"] == "failed"
    assert tasks_repo.reset_tasks(job["id"], only_failed=True) == 1
    counts = tasks_repo.count_by_status(job["id"])
    assert counts.get("failed", 0) == 0
    assert counts.get("pending", 0) == 2


def test_segments_share_profile_concat_copy(db, tmp_path):
    from app.services.merge import compatible_for_copy
    from app.services.render.episode import render_episode_segment

    src = _fixture_mp4(tmp_path / "fix" / "ep.mp4")
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    segs = []
    for i in (1, 2):
        raw = work / f"raw_{i}.mp4"
        raw.write_bytes(src.read_bytes())
        out = work / f"seg_{i:03d}.mp4"
        render_episode_segment(raw, out, template_frame=None,
                               canvas=(1280, 720, 0, 0, 1280, 720))
        segs.append(out)
    assert compatible_for_copy(segs) is True
    from app.services.media.drama_media import probe_media

    for s in segs:
        pr = probe_media(s)
        assert (pr["width"], pr["height"]) == (1280, 720)
        assert pr["codec"] == "h264"


def test_final_duration_matches_segments(db, tmp_path):
    _p, series = _seed_series(db, n=2, prefix="dursum")
    src = _fixture_mp4(tmp_path / "fix" / "ep.mp4")

    async def fake_download(ep, target):
        target.write_bytes(src.read_bytes())

    async def fake_upload(job, final_path):
        from app.services.media.drama_media import probe_media

        pr = probe_media(final_path)
        assert abs(pr["duration"] - 2.0) < 1.5
        return {"youtube_video_id": "yt_d"}

    job = proc.create_job(_pipeline_of(series), series["id"], "direct_merge", 0, 1, 2)
    out = run(run_series_job(
        job["id"], workdir=tmp_path / "work", download_episode=fake_download,
        upload_video=fake_upload,
    ))
    assert out["status"] == "completed", out


def test_job_episodes_and_retry_endpoints(db):
    from fastapi.testclient import TestClient

    from app.db.repositories import episode_tasks as tasks_repo
    from app.main import create_app

    _p, series = _seed_series(db, n=2, prefix="api")
    job = proc.create_job(_pipeline_of(series), series["id"], "direct_merge", 0, 1, 2)
    tasks_repo.ensure_tasks(
        job["id"],
        [{"id": "dep_a", "episode_number": 1}, {"id": "dep_b", "episode_number": 2}],
    )
    tasks_repo.mark_status(job["id"], "dep_a", "rendered")
    tasks_repo.mark_status(job["id"], "dep_b", "failed",
                           last_error_code="X", last_error_message="y")
    client = TestClient(create_app())
    r = client.get(
        f"/api/drama/series-jobs/{job['id']}/episodes",
        headers={"X-Admin-Token": "test_admin_token"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["counts"].get("rendered") == 1
    rr = client.post(
        f"/api/drama/series-jobs/{job['id']}/retry",
        headers={"X-Admin-Token": "test_admin_token"},
        json={"failed_only": True},
    )
    assert rr.status_code == 200, rr.text
    assert rr.json()["reset"] == 1
    rr2 = client.post(
        f"/api/drama/series-jobs/{job['id']}/retry",
        headers={"X-Admin-Token": "test_admin_token"},
        json={"episode_numbers": [1]},
    )
    assert rr2.json()["reset"] == 1
    bad = client.post(
        f"/api/drama/series-jobs/{job['id']}/retry",
        headers={"X-Admin-Token": "test_admin_token"},
        json={},
    )
    assert bad.status_code == 400
    missing = client.post(
        "/api/drama/series-jobs/djob_nope/retry",
        headers={"X-Admin-Token": "test_admin_token"},
        json={"failed_only": True},
    )
    assert missing.status_code == 404
