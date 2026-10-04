"""YouTube scheduled-publication reconciler tests (Task 10)."""

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
from app.db.repositories import destinations, pipelines, publications, reels, schedules, sources
from app.main import create_app
from app.services.youtube_schedule_reconciler import reconcile_due_scheduled_publications

TEST_DB_PATH = Path("/tmp/backend_facebook_task10_reconciler_test.db")
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


def test_reconciler_idempotent(db) -> None:
    pipe = make_pipeline("r1")
    src = make_source("r1")
    dest = make_destination("r1")
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
    batch = asyncio.run(schedules.get_batch(pipe["id"], dest["id"], "2026-10-05"))
    assert batch is not None
    result1 = asyncio.run(reconcile_due_scheduled_publications(limit=20))
    result2 = asyncio.run(reconcile_due_scheduled_publications(limit=20))
    assert result1["checked"] == result2["checked"]
