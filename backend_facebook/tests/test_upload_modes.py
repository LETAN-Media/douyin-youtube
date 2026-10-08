"""YouTube upload modes: video (default) vs shorts.

Video mode uploads untouched. Shorts mode verifies the real file with
ffprobe (<=180s, vertical/square) and fails loud instead of trimming.
"""

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_scheduler import (  # noqa: F401  (module-local db fixture)
    AUTH_HEADERS,
    db,
    make_pipeline,
)

FFMPEG = shutil.which("ffmpeg")

requires_ffmpeg = pytest.mark.skipif(
    FFMPEG is None, reason="ffmpeg/ffprobe not installed"
)


def _make_video(path: Path, *, duration: int, width: int, height: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", f"testsrc=duration={duration}:size={width}x{height}:rate=15",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True, timeout=120,
    )
    return path


def test_normalize_upload_mode_defaults_and_validation():
    from app.db.repositories.pipelines import normalize_upload_mode

    assert normalize_upload_mode(None) == "video"
    assert normalize_upload_mode("") == "video"
    assert normalize_upload_mode("SHORTS") == "shorts"
    assert normalize_upload_mode(" video ") == "video"
    with pytest.raises(ValueError):
        normalize_upload_mode("vertical")


def test_check_shorts_eligibility_matrix(tmp_path):
    from app.services.facebook_shorts import check_shorts_eligibility

    if FFMPEG is None:
        pytest.skip("ffmpeg/ffprobe not installed")
    short_vertical = _make_video(tmp_path / "sv.mp4", duration=5, width=540, height=960)
    ok, note = check_shorts_eligibility(short_vertical)
    assert ok is True, note
    assert "540x960" in note
    square = _make_video(tmp_path / "sq.mp4", duration=5, width=480, height=480)
    ok, _ = check_shorts_eligibility(square)
    assert ok is True
    landscape = _make_video(tmp_path / "ls.mp4", duration=5, width=960, height=540)
    ok, note = check_shorts_eligibility(landscape)
    assert ok is False
    assert "ngang" in note


def test_check_shorts_missing_binary(monkeypatch, tmp_path):
    import app.services.facebook_shorts as shorts_mod

    monkeypatch.setattr(shorts_mod.shutil, "which", lambda name: None)
    with pytest.raises(shorts_mod.ShortsCheckError) as exc:
        shorts_mod.check_shorts_eligibility(tmp_path / "x.mp4")
    assert exc.value.code == "SHORTS_CHECK_UNAVAILABLE"


def test_pipeline_mode_roundtrip_and_legacy_default(db):
    from fastapi.testclient import TestClient

    from app.main import create_app

    client = TestClient(create_app())
    headers = {"X-Admin-Token": "test_admin_token"}
    pipe = client.post(
        "/api/facebook/pipelines", headers=headers, json={"name": "Mode Pipe"}
    ).json()
    # Legacy default: video (column default, no explicit set).
    assert pipe["youtube_upload_mode"] == "video"
    bad = client.patch(
        f"/api/facebook/pipelines/{pipe['id']}",
        headers=headers, json={"youtube_upload_mode": "vertical"},
    )
    assert bad.status_code == 400
    assert bad.json()["error"] == "INVALID_UPLOAD_MODE"
    ok = client.patch(
        f"/api/facebook/pipelines/{pipe['id']}",
        headers=headers, json={"youtube_upload_mode": "shorts"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["youtube_upload_mode"] == "shorts"
    # Reload persists.
    again = client.get(f"/api/facebook/pipelines/{pipe['id']}", headers=headers)
    assert again.json()["youtube_upload_mode"] == "shorts"


def test_scheduler_snapshots_mode_at_enqueue(db):
    import app.db.repositories.publications as pubs_repo
    from app.db.repositories import pipelines as pipes_repo

    async def _go():
        pipe = await pipes_repo.create_pipeline(
            pipeline_id="pl_mode_test", name="Mode Test", slug="mode-test"
        )
        assert pipe["youtube_upload_mode"] == "video"
        await pipes_repo.update_pipeline("pl_mode_test", youtube_upload_mode="shorts")
        updated = await pipes_repo.get_pipeline("pl_mode_test")
        assert updated is not None and updated["youtube_upload_mode"] == "shorts"
        pub, created = await pubs_repo.get_or_create(
            publication_id="pub_mode_1", reel_db_id="reel_x",
            destination_id="dest_x",
        )
        assert created is True
        await pubs_repo.set_upload_snapshot(pub["id"], updated["youtube_upload_mode"])
        row = await pubs_repo.get_publication(pub["id"])
        assert row is not None and row["youtube_upload_mode"] == "shorts"
        # Changing pipeline afterwards must not rewrite the snapshot here;
        # snapshot only changes on (re)enqueue.
        await pipes_repo.update_pipeline("pl_mode_test", youtube_upload_mode="video")
        row2 = await pubs_repo.get_publication(pub["id"])
        assert row2 is not None and row2["youtube_upload_mode"] == "shorts"

    asyncio.run(_go())


def test_shorts_check_recorded_on_publication(db):
    import app.db.repositories.publications as pubs_repo

    async def _go():
        pub, _ = await pubs_repo.get_or_create(
            publication_id="pub_mode_2", reel_db_id="reel_y",
            destination_id="dest_y",
        )
        await pubs_repo.set_shorts_check(pub["id"], True, "5s · 540x960 vertical")
        row = await pubs_repo.get_publication(pub["id"])
        assert row is not None
        assert row["shorts_eligible"] is True
        assert "540x960" in (row["shorts_check_note"] or "")

    asyncio.run(_go())
