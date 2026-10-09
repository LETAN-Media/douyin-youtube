"""P0 Regression Tests: Audio Truyện auto pipeline scheduler & job safety."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

ADMIN = {"X-Admin-Token": "test_admin_token"}


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


def _add_background(pid, enabled=1):
    from app.db.client import get_client
    from app.db.repositories import new_id, now_iso

    aid = new_id("amedia")
    client = get_client()
    client.execute(
        "INSERT INTO audio_media_assets (id, pipeline_id, kind, object_key, file_name, "
        "enabled, created_at, updated_at) VALUES (?, ?, 'background', ?, 'bg.mp4', ?, ?, ?)",
        (aid, pid, f"bgs/{aid}.mp4", enabled, now_iso(), now_iso()))
    client.commit()
    return aid


# 1. Turso COUNT trả "1" (string) -> không TypeError, và COUNT trả 1 -> hoạt động bình thường
def test_turso_count_string_no_type_error(db, client, monkeypatch):
    from app.db import client as db_client
    from app.services import scheduler

    pid = _setup_pipeline(client)
    _add_dest(pid)
    _add_background(pid, enabled=1)

    # Enable scheduler with max 2 videos/day
    from app.db.repositories import audio as audio_repo
    audio_repo.upsert_scheduler_settings(pid, enabled=True, max_videos_per_day=2)

    real_get_client = db_client.get_client

    class MockQueryResult:
        def __init__(self, val):
            self.val = val

        def fetchone(self):
            return {"n": self.val}

    class MockClient:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, params=()):
            if "SELECT COUNT(*) AS n FROM audio_publications" in sql:
                return MockQueryResult("1")  # Return string '1' like Turso
            return self._inner.execute(sql, params)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(db_client, "get_client", lambda: MockClient(real_get_client()))

    due, reason = scheduler.pipeline_due(pid)
    # Should evaluate string '1' < 2 without throwing TypeError!
    assert due is True
    assert reason == "due"

    # Now simulate COUNT(*) returning '2' (string) -> should hit daily cap without error
    class MockClientCap:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, params=()):
            if "SELECT COUNT(*) AS n FROM audio_publications" in sql:
                return MockQueryResult("2")  # Return string '2'
            return self._inner.execute(sql, params)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(db_client, "get_client", lambda: MockClientCap(real_get_client()))
    due, reason = scheduler.pipeline_due(pid)
    assert due is False
    assert reason == "daily cap reached"


# 2. Scheduler ON + 200 video -> xác định được trạng thái due
def test_scheduler_on_with_200_videos_is_due(db, client):
    from app.db.repositories import audio as audio_repo
    from app.db.repositories import sources as src_repo
    from app.services import scheduler

    pid = _setup_pipeline(client)
    _add_dest(pid)
    _add_background(pid, enabled=1)
    audio_repo.upsert_scheduler_settings(pid, enabled=True, max_videos_per_day=3)

    # Insert 200 available items into inventory
    for i in range(200):
        src_repo.upsert_inventory_item(
            pid, None, f"fb_vid_{i}", f"https://www.facebook.com/reel/{i}/")

    due, reason = scheduler.pipeline_due(pid)
    assert due is True
    assert reason == "due"

    out = scheduler.tick_pipeline(pid)
    assert out["due"] is True
    assert out["reason"] == "queued"
    assert out["job_id"] is not None


# 3. Không có background -> trả về blocker NO_BACKGROUND và không tạo job
def test_no_background_blocks_job_creation(db, client):
    from app.db.repositories import audio as audio_repo
    from app.db.repositories import jobs as jobs_repo
    from app.db.repositories import sources as src_repo
    from app.services import scheduler

    pid = _setup_pipeline(client)
    _add_dest(pid)
    # Do NOT add any enabled background
    audio_repo.upsert_scheduler_settings(pid, enabled=True)

    src_repo.upsert_inventory_item(
        pid, None, "fb_vid_1", "https://www.facebook.com/reel/1/")

    due, reason = scheduler.pipeline_due(pid)
    assert due is False
    assert reason == "NO_BACKGROUND"

    # tick_pipeline must NOT reserve video and NOT create a job
    out = scheduler.tick_pipeline(pid)
    assert out["due"] is False
    assert out["reason"] == "NO_BACKGROUND"
    assert len(jobs_repo.list_jobs(pid)) == 0

    # Verify inventory item remained available, not reserved
    items, _ = src_repo.list_inventory(pid)
    assert items[0]["status"] == "available"


# 4. Chưa đến giờ đăng (daily_times) -> không tạo job
def test_daily_times_outside_window_does_not_create_job(db, client):
    from app.db.repositories import audio as audio_repo
    from app.services import scheduler

    pid = _setup_pipeline(client)
    _add_dest(pid)
    _add_background(pid, enabled=1)

    # Configure daily_times at 03:00 and 04:00 (outside current test time or far future)
    audio_repo.upsert_scheduler_settings(
        pid, enabled=True, daily_times=["03:00", "04:00"], timezone="UTC")

    # If current UTC is not 03:00 or 04:00 (within 30m)
    now_utc = datetime.now(timezone.utc)
    if not (now_utc.hour in (3, 4) and now_utc.minute < 30):
        due, reason = scheduler.pipeline_due(pid)
        assert due is False
        assert reason == "waiting for next_run_at"


# 5. Job failed -> khôi phục inventory an toàn, tránh retry vô hạn
def test_job_failure_recovers_inventory_safely(db, client):
    from app.db.repositories import jobs as jobs_repo
    from app.db.repositories import sources as src_repo
    from app.services import processing

    pid = _setup_pipeline(client)
    item, _ = src_repo.upsert_inventory_item(
        pid, None, "fb_100", "https://www.facebook.com/reel/100/")

    job1 = jobs_repo.create_job(pid, inventory_id=item["id"], mode="auto")
    src_repo.set_inventory_status(item["id"], "processing")

    # First transient failure -> should recover inventory back to 'available'
    processing._fail(job1["id"], "NETWORK_ERROR", "Temporary network drop", "downloading",
                     inventory_id=item["id"])
    refreshed, _ = src_repo.list_inventory(pid)
    assert refreshed[0]["status"] == "available"

    # Second failure for same item -> exceeded retry limit, marks as 'failed' (no infinite retry)
    job2 = jobs_repo.create_job(pid, inventory_id=item["id"], mode="auto")
    src_repo.set_inventory_status(item["id"], "processing")
    processing._fail(job2["id"], "NETWORK_ERROR", "Second failure", "downloading",
                     inventory_id=item["id"])
    refreshed2, _ = src_repo.list_inventory(pid)
    assert refreshed2[0]["status"] == "failed"

    # Permanent error code immediately marks as 'failed'
    item_perm, _ = src_repo.upsert_inventory_item(
        pid, None, "fb_perm", "https://www.facebook.com/reel/perm/")
    job3 = jobs_repo.create_job(pid, inventory_id=item_perm["id"], mode="auto")
    src_repo.set_inventory_status(item_perm["id"], "processing")
    processing._fail(job3["id"], "NO_SOURCE", "No source found", "resolving",
                     inventory_id=item_perm["id"])
    refreshed3, _ = src_repo.list_inventory(pid)
    assert [i for i in refreshed3 if i["id"] == item_perm["id"]][0]["status"] == "failed"


# 6. Job completed -> xóa last_error_code và last_error_message cũ
def test_job_completed_clears_old_errors(db, client):
    from app.db.repositories import jobs as jobs_repo

    pid = _setup_pipeline(client)
    job = jobs_repo.create_job(pid, mode="manual")

    # Simulate an error recorded previously
    jobs_repo.update_job(job["id"], last_error_code="NO_BACKGROUND",
                         last_error_message="Pipeline media library has no enabled background.")
    j_err = jobs_repo.get_job(job["id"])
    assert j_err["last_error_code"] == "NO_BACKGROUND"

    # Mark completed -> must clear error code and message
    jobs_repo.update_job(job["id"], status="completed", stage="completed:done",
                         progress_percent=100)
    j_done = jobs_repo.get_job(job["id"])
    assert j_done["status"] == "completed"
    assert j_done["last_error_code"] is None
    assert j_done["last_error_message"] is None


# 7. Pipeline manual -> không bao giờ được auto schedule
def test_manual_pipeline_never_auto_scheduled(db, client):
    from app.db.repositories import audio as audio_repo
    from app.services import scheduler

    pid = _setup_pipeline(client, name="Thủ Công", p_type="manual")
    _add_dest(pid)
    _add_background(pid, enabled=1)
    audio_repo.upsert_scheduler_settings(pid, enabled=True)

    due, reason = scheduler.pipeline_due(pid)
    assert due is False
    assert reason == "manual pipeline"


# 8. Không quét Facebook trong scheduler
def test_scheduler_never_scans_facebook(db, client):
    import inspect
    from app.services import scheduler

    src = inspect.getsource(scheduler)
    assert "scan_source" not in src
    assert "import scanner" not in src


# 9. Không tạo hai job cho cùng video
def test_no_duplicate_jobs_for_same_video(db, client):
    from app.db.repositories import jobs as jobs_repo
    from app.db.repositories import sources as src_repo

    pid = _setup_pipeline(client)
    item, _ = src_repo.upsert_inventory_item(
        pid, None, "fb_dup_1", "https://www.facebook.com/reel/dup_1/")

    job1 = jobs_repo.create_job(pid, inventory_id=item["id"], mode="auto")
    job2 = jobs_repo.create_job(pid, inventory_id=item["id"], mode="auto")
    assert job1["id"] == job2["id"]


# 10. /ready endpoint kiểm tra worker status
def test_ready_endpoint_checks_worker(db, monkeypatch):
    from app.workers import audio_worker

    app = create_app()
    with TestClient(app) as c:
        # When worker is not running, /ready should return 503
        monkeypatch.setattr(audio_worker, "status", lambda: {"running": False})
        r = c.get("/ready")
        assert r.status_code == 503
        assert r.json()["reason"] == "worker not running"

        # When worker is running, /ready returns 200
        monkeypatch.setattr(audio_worker, "status", lambda: {"running": True})
        r = c.get("/ready")
        assert r.status_code == 200
        assert r.json()["ready"] is True
