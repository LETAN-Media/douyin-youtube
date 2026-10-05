"""Manual "run batch now" semantics.

Covers the manual vs automatic split around batch_time, future-slot-only
selection, double-click idempotency, the NO_AI_READY_INVENTORY reason, and the
guarantee that the request performs no download/upload itself.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db.repositories import ai_metadata, publish_queue, schedules
from app.services.facebook_scheduler import execute_daily_batch, run_scheduler_tick
from app.main import create_app
from tests.test_scheduler import (  # noqa: F401  (module-local db fixture)
    AUTH_HEADERS,
    db,
    make_destination,
    make_pipeline,
    make_source,
    seed_reel,
)

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
# 2026-10-05 is a Monday (weekday 0).
MONDAY = "2026-10-05"


def _at(hour: int, minute: int) -> datetime:
    """Local ICT time -> UTC instant."""
    return datetime(2026, 10, 5, hour, minute, tzinfo=TZ).astimezone(timezone.utc)


def _enable(suffix: str, *, batch_time: str = "06:00", slots: dict | None = None,
            max_daily: int = 5) -> tuple[dict, dict, dict]:
    pipe = make_pipeline(suffix)
    src = make_source(suffix)
    dest = make_destination(suffix)
    client = TestClient(create_app())
    body = {"enabled": True, "max_daily_publish": max_daily, "batch_time": batch_time}
    if slots is not None:
        names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        body["slots"] = {names[day]: times for day, times in slots.items()}
    r = client.put(
        f"/api/facebook/pipelines/{pipe['id']}/schedule",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        json=body,
    )
    assert r.status_code == 200, r.text
    return pipe, src, dest


def _mark_ai_ready(pipeline_id: str, reel_db_id: str) -> None:
    """Give a reel generated AI metadata matching the pipeline's current config."""
    from app.db.repositories import ai_settings as ai_settings_repo

    async def _run() -> None:
        pipe_ai = await ai_settings_repo.get_settings(pipeline_id)
        model = settings.TOOLNET_MODEL or ""
        config_hash = ai_settings_repo.compute_config_hash(
            enabled=pipe_ai.get("enabled", True),
            system_prompt=pipe_ai.get("system_prompt"),
            title_template=pipe_ai.get("title_template"),
            description_template=pipe_ai.get("description_template"),
            locked_hashtags=pipe_ai.get("locked_hashtags"),
            language=pipe_ai.get("language"),
            model=model,
        )
        await ai_metadata.upsert_generated(
            reel_db_id=reel_db_id,
            title="Tiêu đề AI",
            description="Mô tả AI",
            hashtags=["x"],
            model=model,
            config_hash=config_hash,
            source_hash=f"src_{reel_db_id}",
        )

    asyncio.run(_run())


# ---------- A. manual run bypasses batch_time ----------
def test_manual_run_bypasses_batch_time(db) -> None:
    pipe, src, dest = _enable("ma")
    seed_reel(src["id"], "r1")
    _mark_ai_ready(pipe["id"], f"{src['id']}_r1")

    # 02:00 ICT is well before batch_time 06:00.
    result = asyncio.run(
        execute_daily_batch(pipe["id"], dest["id"], force_now=True, now=_at(2, 0))
    )

    assert result["videos_enqueued"] == 1, result
    assert result["reason"] is None
    assert len(result["slots"]) == 1
    stats = asyncio.run(publish_queue.get_queue_stats())
    assert stats["queued"] == 1, stats


# ---------- B. automatic tick still respects batch_time ----------
def test_auto_tick_respects_batch_time(db) -> None:
    pipe, src, dest = _enable("mb")
    seed_reel(src["id"], "r1")
    _mark_ai_ready(pipe["id"], f"{src['id']}_r1")

    tick = asyncio.run(run_scheduler_tick(now=_at(2, 0)))

    assert tick["videos_enqueued"] == 0, tick
    assert tick["batches_started"] == 0, tick
    stats = asyncio.run(publish_queue.get_queue_stats())
    assert stats["total"] == 0, stats
    # The gate must run BEFORE the daily UNIQUE row is inserted, otherwise the
    # 06:00 automatic run would be blocked by an already-claimed batch.
    batch = asyncio.run(schedules.get_batch(pipe["id"], dest["id"], MONDAY))
    assert batch is None, batch

    # Once batch_time has passed, the same tick does enqueue.
    tick_after = asyncio.run(run_scheduler_tick(now=_at(7, 0)))
    assert tick_after["videos_enqueued"] == 1, tick_after


# ---------- C. manual run uses future slots only ----------
def test_manual_run_uses_future_slots_only(db) -> None:
    slots = {0: ["09:00", "11:00", "15:30", "19:00", "21:00"]}
    pipe, src, dest = _enable("mc", slots=slots)
    for i in range(5):
        seed_reel(src["id"], f"r{i}")
        _mark_ai_ready(pipe["id"], f"{src['id']}_r{i}")

    # 12:35 ICT: 09:00 and 11:00 are already past.
    result = asyncio.run(
        execute_daily_batch(pipe["id"], dest["id"], force_now=True, now=_at(12, 35))
    )

    assert result["videos_enqueued"] == 3, result
    assert [s["slot"] for s in result["slots"]] == ["15:30", "19:00", "21:00"]
    # 15:30 ICT == 08:30 UTC, so nothing lands in the past.
    assert result["slots"][0]["publish_at"] == "2026-10-05T08:30:00Z"


# ---------- D. double click does not duplicate ----------
def test_manual_double_click_is_idempotent(db) -> None:
    pipe, src, dest = _enable("md")
    seed_reel(src["id"], "r1")
    _mark_ai_ready(pipe["id"], f"{src['id']}_r1")

    first = asyncio.run(
        execute_daily_batch(pipe["id"], dest["id"], force_now=True, now=_at(12, 0))
    )
    second = asyncio.run(
        execute_daily_batch(pipe["id"], dest["id"], force_now=True, now=_at(12, 1))
    )

    assert first["videos_enqueued"] == 1, first
    assert second["videos_enqueued"] == 1, second  # reports the existing total
    assert second["reason"] == "BATCH_ALREADY_COMPLETED", second
    assert second["batch_id"] == first["batch_id"]

    stats = asyncio.run(publish_queue.get_queue_stats())
    assert stats["queued"] == 1, stats

    from app.db.repositories import publications

    rows = asyncio.run(
        __import__("app.db.client", fromlist=["get_client"]).get_client().execute(
            "SELECT COUNT(*) FROM publications WHERE destination_id = :d",
            {"d": dest["id"]},
        )
    )
    assert rows.rows[0][0] == 1, rows.rows
    assert asyncio.run(publications.get_by_reel_destination(f"{src['id']}_r1", dest["id"]))


# ---------- E. manual run with no AI-ready inventory ----------
def test_manual_run_without_ai_ready_inventory(db) -> None:
    pipe, src, dest = _enable("me")
    seed_reel(src["id"], "r1")  # no AI metadata

    result = asyncio.run(
        execute_daily_batch(pipe["id"], dest["id"], force_now=True, now=_at(12, 0))
    )

    assert result["videos_enqueued"] == 0, result
    assert result["reason"] == "NO_AI_READY_INVENTORY", result
    assert result["message"], "a zero-enqueue result must carry an explanation"
    stats = asyncio.run(publish_queue.get_queue_stats())
    assert stats["total"] == 0, stats


# ---------- E2. no future slots left today ----------
def test_manual_run_after_last_slot_reports_no_future_slots(db) -> None:
    slots = {0: ["09:00"]}
    pipe, src, dest = _enable("mf", slots=slots)
    seed_reel(src["id"], "r1")
    _mark_ai_ready(pipe["id"], f"{src['id']}_r1")

    result = asyncio.run(
        execute_daily_batch(pipe["id"], dest["id"], force_now=True, now=_at(12, 0))
    )

    assert result["videos_enqueued"] == 0, result
    assert result["reason"] == "NO_FUTURE_SLOTS", result


# ---------- F. the request itself does no download/upload ----------
def test_manual_request_performs_no_download_or_upload(db, monkeypatch) -> None:
    from app.services import facebook_global_publisher as gp
    from app.services.facebook_media import FacebookMediaResolver

    pipe, src, dest = _enable("mg")
    seed_reel(src["id"], "r1")
    _mark_ai_ready(pipe["id"], f"{src['id']}_r1")

    def _boom(*args, **kwargs):
        raise AssertionError("manual batch run must not do heavy work in-request")

    # FastSaver resolve + download, YouTube upload, and inline queue processing.
    monkeypatch.setattr(FacebookMediaResolver, "resolve", _boom)
    monkeypatch.setattr(FacebookMediaResolver, "download_media", _boom)
    monkeypatch.setattr(gp, "upload_video", _boom)
    monkeypatch.setattr(gp, "run_publisher_once", _boom)

    client = TestClient(create_app())
    r = client.post(
        f"/api/facebook/pipelines/{pipe['id']}/youtube-destinations/{dest['id']}/schedule-today",
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "executed", body
    assert body["videos_enqueued"] == 1, body
    assert len(body["slots"]) == 1, body
    assert body["reason"] is None, body

    # Work is parked in the durable queue for the sequential publisher worker.
    stats = asyncio.run(publish_queue.get_queue_stats())
    assert stats["queued"] == 1, stats
    assert stats["published"] == 0, stats
    assert stats["failed"] == 0, stats


# ---------- F2. route surfaces a reason instead of a false "executed" ----------
def test_manual_route_reports_reason_when_nothing_enqueued(db) -> None:
    pipe, src, dest = _enable("mh")
    seed_reel(src["id"], "r1")  # no AI metadata

    client = TestClient(create_app())
    r = client.post(
        f"/api/facebook/pipelines/{pipe['id']}/youtube-destinations/{dest['id']}/schedule-today",
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False, body
    assert body["status"] != "executed", body
    assert body["videos_enqueued"] == 0, body
    assert body["reason"] == "NO_AI_READY_INVENTORY", body
    assert body["message"], body


# ---------- F3. route double click stays idempotent ----------
def test_manual_route_double_click_is_idempotent(db) -> None:
    pipe, src, dest = _enable("mi")
    seed_reel(src["id"], "r1")
    _mark_ai_ready(pipe["id"], f"{src['id']}_r1")

    client = TestClient(create_app())
    url = f"/api/facebook/pipelines/{pipe['id']}/youtube-destinations/{dest['id']}/schedule-today"
    first = client.post(url, headers=AUTH_HEADERS)
    second = client.post(url, headers=AUTH_HEADERS)

    assert first.json()["videos_enqueued"] == 1, first.json()
    assert second.json()["reason"] == "BATCH_ALREADY_COMPLETED", second.json()
    stats = asyncio.run(publish_queue.get_queue_stats())
    assert stats["queued"] == 1, stats