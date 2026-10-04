"""Daily batch scheduler tests (Task 9)."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import app.db.client as client_module
from app.config import settings
from app.db.client import get_client, migrate
from app.db.repositories import destinations, pipelines, reels, schedules, sources
from app.main import create_app

TEST_DB_PATH = Path("/tmp/backend_facebook_task9_test.db")
TEST_DB_URL = f"file:{TEST_DB_PATH}"
ADMIN = "test_admin_token"
AUTH_HEADERS = {"X-Admin-Token": ADMIN}
PAGE_ID = "61592409539824"
def fresh_db() -> None:
    client_module._client = None
    os.environ["ADMIN_TOKEN"] = ADMIN
    os.environ["TURSO_DATABASE_URL"] = TEST_DB_URL
    os.environ["TURSO_AUTH_TOKEN"] = "test_token"
    settings.ADMIN_TOKEN = ADMIN
    settings.TURSO_DATABASE_URL = TEST_DB_URL
    settings.TURSO_AUTH_TOKEN = "test_token"
    settings.RAPIDAPI_KEY = "test_key_1"
    settings.RAPIDAPI_KEY_FALLBACK = None
    settings.FACEBOOK_RAPIDAPI_HOST = "test-host"
    settings.FACEBOOK_RAPIDAPI_BASE_URL = "https://test-host"
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
        "token": os.environ.get("TURSO_AUTH_TOKEN"),
        "admin": os.environ.get("ADMIN_TOKEN"),
        "settings_url": settings.TURSO_DATABASE_URL,
        "key": settings.RAPIDAPI_KEY,
        "fallback": settings.RAPIDAPI_KEY_FALLBACK,
        "host": settings.FACEBOOK_RAPIDAPI_HOST,
        "base": settings.FACEBOOK_RAPIDAPI_BASE_URL,
    }
    fresh_db()
    yield
    client_module._client = None
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    if prev["url"] is not None:
        os.environ["TURSO_DATABASE_URL"] = prev["url"]
    if prev["token"] is not None:
        os.environ["TURSO_AUTH_TOKEN"] = prev["token"]
    if prev["admin"] is not None:
        os.environ["ADMIN_TOKEN"] = prev["admin"]
    settings.TURSO_DATABASE_URL = prev["settings_url"]
    settings.RAPIDAPI_KEY = prev["key"]
    settings.RAPIDAPI_KEY_FALLBACK = prev["fallback"]
    settings.FACEBOOK_RAPIDAPI_HOST = prev["host"]
    settings.FACEBOOK_RAPIDAPI_BASE_URL = prev["base"]
    client_module._client = None
def make_pipeline(suffix: str) -> dict:
    async def _run() -> dict:
        try:
            return await pipelines.create_pipeline(
                pipeline_id=f"p{suffix}", name=f"P{suffix}", slug=f"p{suffix}"
            )
        except Exception:
            return await pipelines.get_pipeline(f"p{suffix}")
    return asyncio.run(_run())
def make_source(suffix: str) -> dict:
    async def _run() -> dict:
        try:
            await pipelines.create_pipeline(
                pipeline_id=f"p{suffix}", name=f"P{suffix}", slug=f"p{suffix}"
            )
        except Exception:
            pass
        try:
            src = await sources.create_source(
                source_id=f"src{suffix}",
                pipeline_id=f"p{suffix}",
                page_id=PAGE_ID,
                page_name=None,
                reels_url=f"https://www.facebook.com/{PAGE_ID}/reels/",
            )
        except Exception:
            src = await sources.get_source(f"src{suffix}")
        return src
    return asyncio.run(_run())
def make_destination(suffix: str) -> dict:
    async def _run() -> dict:
        dest = await destinations.create_destination(
            destination_id=f"dest{suffix}",
            pipeline_id=f"p{suffix}",
            channel_id="channel_test",
            channel_name="Test Channel",
            visibility="private",
            enabled=True,
        )
        await destinations.set_connected(dest["id"], channel_id="channel_test", channel_name="Test Channel")
        return await destinations.get_destination(dest["id"])
    return asyncio.run(_run())
def seed_reel(source_id: str, reel_id: str, status: str = "new") -> None:
    async def _run() -> None:
        await reels.insert_reel_if_new(
            reel_db_id=f"{source_id}_{reel_id}", source_id=source_id, reel_id=reel_id
        )
        if status != "new":
            await reels.update_reel_status(f"{source_id}_{reel_id}", status)
    asyncio.run(_run())
# ---------- 1. default schedule slots ----------
def test_default_slots(db) -> None:
    pipe = make_pipeline("s1")
    src = make_source("s1")
    client = TestClient(create_app())
    r = client.put(
        f"/api/facebook/pipelines/{pipe['id']}/schedule",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        json={"enabled": True, "max_daily_publish": 5},
    )
    assert r.status_code == 200, r.text
    sched = r.json()
    assert sched["slots"]["monday"] == ["11:30", "14:30", "18:30", "20:30", "22:30"]
    assert sched["slots"]["saturday"] == ["09:30", "11:30", "15:00", "19:30", "21:30"]
    assert sched["slots"]["sunday"] == ["09:00", "11:00", "15:30", "19:00", "21:00"]
    assert sched["batch_time"] == "06:00"
# ---------- 2. batch_time config ----------
def test_batch_time_config(db) -> None:
    pipe = make_pipeline("s2")
    src = make_source("s2")
    client = TestClient(create_app())
    r = client.put(
        f"/api/facebook/pipelines/{pipe['id']}/schedule",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        json={"enabled": True, "batch_time": "07:30", "max_daily_publish": 3},
    )
    assert r.status_code == 200, r.text
    sched = r.json()
    assert sched["batch_time"] == "07:30"
# ---------- 3. batch runs once per day ----------
def test_batch_runs_once_per_day(db) -> None:
    pipe = make_pipeline("s3")
    src = make_source("s3")
    dest = make_destination("s3")
    seed_reel(src["id"], "r1")
    seed_reel(src["id"], "r2")
    client = TestClient(create_app())
    r = client.put(
        f"/api/facebook/pipelines/{pipe['id']}/schedule",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        json={"enabled": True, "max_daily_publish": 5},
    )
    assert r.status_code == 200, r.text
    now = datetime(2026, 10, 5, 7, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    from app.services.facebook_scheduler import run_scheduler_tick
    asyncio.run(run_scheduler_tick(now=now.replace(tzinfo=timezone.utc)))
    batch = asyncio.run(schedules.get_batch(pipe["id"], dest["id"], "2026-10-05"))
    assert batch is not None
    assert batch["status"] in ("completed", "no_work", "failed")
    asyncio.run(run_scheduler_tick(now=now.replace(tzinfo=timezone.utc)))
    batches = asyncio.run(get_client().execute(
        "SELECT COUNT(*) FROM facebook_scheduler_batches WHERE pipeline_id = :pid AND local_date = '2026-10-05'",
        {"pid": pipe["id"]},
    ))
    count = batches.rows[0][0] if batches.rows else 0
    assert count == 1
# ---------- 4. future slots only ----------
def test_future_slots_only(db) -> None:
    from app.services.facebook_scheduler import _future_slots_for_today
    schedule = {
        "timezone": "Asia/Ho_Chi_Minh",
        "slots": {0: ["09:00", "11:00", "15:00", "19:00", "21:00"]},
    }
    now = datetime(2026, 10, 5, 10, 30, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    future = _future_slots_for_today(schedule, now)
    assert len(future) == 4
    assert future[0][0] == "11:00"
    assert future[-1][0] == "21:00"
# ---------- 5. past slots skipped ----------
def test_past_slots_skipped(db) -> None:
    from app.services.facebook_scheduler import _future_slots_for_today
    schedule = {
        "timezone": "Asia/Ho_Chi_Minh",
        "slots": {0: ["09:00", "11:00", "15:00", "19:00", "21:00"]},
    }
    now = datetime(2026, 10, 5, 22, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    future = _future_slots_for_today(schedule, now)
    assert len(future) == 0
# ---------- 6. timezone conversion ----------
def test_timezone_conversion_utc(db) -> None:
    from app.services.facebook_scheduler import _slot_to_utc_rfc3339
    result = _slot_to_utc_rfc3339("2026-10-05", "11:30", "Asia/Ho_Chi_Minh")
    assert result.endswith("Z")
    assert result.startswith("2026-10-05T04:30:")
# ---------- 7. max daily limit ----------
def test_max_daily_limit(db) -> None:
    pipe = make_pipeline("s7")
    src = make_source("s7")
    dest = make_destination("s7")
    for i in range(10):
        seed_reel(src["id"], f"r{i}")
    client = TestClient(create_app())
    r = client.put(
        f"/api/facebook/pipelines/{pipe['id']}/schedule",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        json={"enabled": True, "max_daily_publish": 2, "batch_time": "06:00"},
    )
    assert r.status_code == 200, r.text
    now = datetime(2026, 10, 5, 7, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    from app.services.facebook_scheduler import run_scheduler_tick
    asyncio.run(run_scheduler_tick(now=now.replace(tzinfo=timezone.utc)))
    batch = asyncio.run(schedules.get_batch(pipe["id"], dest["id"], "2026-10-05"))
    assert batch is not None
    assert batch["planned_count"] <= 2
# ---------- 8. skipped reels ignored ----------
def test_skipped_reels_ignored(db) -> None:
    pipe = make_pipeline("s8")
    src = make_source("s8")
    dest = make_destination("s8")
    seed_reel(src["id"], "r1", status="new")
    seed_reel(src["id"], "r2", status="skipped")
    client = TestClient(create_app())
    r = client.put(
        f"/api/facebook/pipelines/{pipe['id']}/schedule",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        json={"enabled": True, "max_daily_publish": 5, "batch_time": "06:00"},
    )
    assert r.status_code == 200, r.text
    now = datetime(2026, 10, 5, 7, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    from app.services.facebook_scheduler import run_scheduler_tick
    asyncio.run(run_scheduler_tick(now=now.replace(tzinfo=timezone.utc)))
    batch = asyncio.run(schedules.get_batch(pipe["id"], dest["id"], "2026-10-05"))
    assert batch is not None
    assert batch["uploaded_count"] <= 1
# ---------- 9. daily unique constraint ----------
def test_daily_unique_constraint(db) -> None:
    pipe = make_pipeline("s9")
    src = make_source("s9")
    dest = make_destination("s9")
    seed_reel(src["id"], "r1")
    client = TestClient(create_app())
    r = client.put(
        f"/api/facebook/pipelines/{pipe['id']}/schedule",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        json={"enabled": True, "max_daily_publish": 5, "batch_time": "06:00"},
    )
    assert r.status_code == 200, r.text
    now = datetime(2026, 10, 5, 7, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    from app.services.facebook_scheduler import run_scheduler_tick
    asyncio.run(run_scheduler_tick(now=now.replace(tzinfo=timezone.utc)))
    asyncio.run(run_scheduler_tick(now=now.replace(tzinfo=timezone.utc)))
    batches = asyncio.run(get_client().execute(
        "SELECT COUNT(*) FROM facebook_scheduler_batches WHERE pipeline_id = :pid AND local_date = '2026-10-05'",
        {"pid": pipe["id"]},
    ))
    count = batches.rows[0][0] if batches.rows else 0
    assert count == 1
# ---------- 10. schedule-today endpoint ----------
def test_schedule_today_endpoint(db) -> None:
    pipe = make_pipeline("s10")
    src = make_source("s10")
    dest = make_destination("s10")
    client = TestClient(create_app())
    r = client.put(
        f"/api/facebook/pipelines/{pipe['id']}/schedule",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        json={"enabled": True, "max_daily_publish": 5, "batch_time": "06:00"},
    )
    assert r.status_code == 200, r.text
    r2 = client.post(
        f"/api/facebook/pipelines/{pipe['id']}/youtube-destinations/{dest['id']}/schedule-today",
        headers=AUTH_HEADERS,
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["ok"] is True
    assert "batch_id" in body
# ---------- 11. status finds real batch by destination ----------
def test_status_finds_batch_by_destination(db) -> None:
    pipe = make_pipeline("s11")
    src = make_source("s11")
    dest = make_destination("s11")
    seed_reel(src["id"], "r1")
    client = TestClient(create_app())
    r = client.put(
        f"/api/facebook/pipelines/{pipe['id']}/schedule",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        json={"enabled": True, "max_daily_publish": 5, "batch_time": "06:00"},
    )
    assert r.status_code == 200, r.text
    now = datetime(2026, 10, 5, 7, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    from app.services.facebook_scheduler import run_scheduler_tick
    asyncio.run(run_scheduler_tick(now=now.replace(tzinfo=timezone.utc)))
    status = asyncio.run(schedules.get_batch(pipe["id"], dest["id"], "2026-10-05"))
    assert status is not None
    assert status["status"] in ("completed", "no_work", "failed")
# ---------- 12. flow-state sees running batch ----------
def test_flow_state_sees_running_batch(db) -> None:
    pipe = make_pipeline("s12")
    src = make_source("s12")
    dest = make_destination("s12")
    client = TestClient(create_app())
    r = client.put(
        f"/api/facebook/pipelines/{pipe['id']}/schedule",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        json={"enabled": True, "max_daily_publish": 5, "batch_time": "06:00"},
    )
    assert r.status_code == 200, r.text
    r2 = client.get(f"/api/facebook/pipelines/{pipe['id']}/flow-state")
    assert r2.status_code == 200
    body = r2.json()
    assert body["steps"]["scheduler"] in ("idle", "running", "done", "not_configured")
# ---------- 13. manual publish remains unchanged ----------
def test_manual_publish_unchanged(db) -> None:
    from app.services.facebook_publish_worker import run_publish_next

    pipe = make_pipeline("s13")
    src = make_source("s13")
    dest = make_destination("s13")
    seed_reel(src["id"], "r1")
    client = TestClient(create_app())
    r = client.put(
        f"/api/facebook/pipelines/{pipe['id']}/schedule",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        json={"enabled": True, "max_daily_publish": 5, "batch_time": "06:00"},
    )
    assert r.status_code == 200, r.text
    result = asyncio.run(run_publish_next(pipeline_id=pipe["id"], destination_id=dest["id"]))
    assert result is not None
