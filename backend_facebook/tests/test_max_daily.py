"""Configurable Facebook max videos/day and quota-pause behavior.

Regression coverage for the legacy hard-coded 5/day ceiling: values above 5
must persist through the API and the daily scheduler must enqueue up to the
configured max (within available future slots).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import app.db.client as client_module
from app.db.repositories import quota, publish_queue
from app.main import create_app
from app.services.facebook_global_publisher import _pause_for_quota
from app.services.facebook_scheduler import describe_schedule_status, execute_daily_batch
from tests.test_manual_batch import _mark_ai_ready
from tests.test_scheduler import (  # noqa: F401  (module-local db fixture)
    AUTH_HEADERS,
    db,
    make_destination,
    make_pipeline,
    make_source,
    seed_reel,
)

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
WEEKDAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

MONDAY = "2026-10-05"


def _at(hour: int, minute: int) -> datetime:
    return datetime(2026, 10, 5, hour, minute, tzinfo=TZ).astimezone(timezone.utc)


def _slots(count: int) -> list[str]:
    """Unique future-ish HH:MM slots, 03:00 onwards (count <= 20)."""
    return [f"{hour:02d}:00" for hour in range(3, 3 + count)]


def _enable_with_slots(pipeline_id: str, *, max_daily: int, slots: list[str]) -> None:
    client = TestClient(create_app())
    body = {
        "enabled": True,
        "max_daily_publish": max_daily,
        "batch_time": "02:30",
        "slots": {day: slots if day == "monday" else [] for day in WEEKDAY_NAMES},
    }
    response = client.put(
        f"/api/facebook/pipelines/{pipeline_id}/schedule",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        json=body,
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("max_daily", [1, 3, 5, 10, 20, 50, 100])
def test_max_daily_publish_persists_above_five(db, max_daily: int) -> None:
    pipe = make_pipeline(f"mx{max_daily}")
    make_source(f"mx{max_daily}")
    client = TestClient(create_app())

    response = client.put(
        f"/api/facebook/pipelines/{pipe['id']}/schedule",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        json={"enabled": True, "max_daily_publish": max_daily},
    )
    assert response.status_code == 200, response.text
    assert response.json()["max_daily_publish"] == max_daily

    fetched = client.get(
        f"/api/facebook/pipelines/{pipe['id']}/schedule",
        headers=AUTH_HEADERS,
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["max_daily_publish"] == max_daily

    row = asyncio.run(
        client_module.get_client().execute(
            "SELECT max_daily_publish FROM facebook_publish_schedules WHERE pipeline_id = :pid",
            {"pid": pipe["id"]},
        )
    )
    assert row.rows[0][0] == max_daily


def test_auto_generates_slots_when_max_daily_above_default(db) -> None:
    pipe = make_pipeline("mxauto")
    make_source("mxauto")
    client = TestClient(create_app())

    response = client.put(
        f"/api/facebook/pipelines/{pipe['id']}/schedule",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        json={"enabled": True, "max_daily_publish": 8},
    )
    assert response.status_code == 200, response.text
    slots = response.json()["slots"]
    for day in WEEKDAY_NAMES:
        assert len(slots[day]) == 8, (day, slots[day])
        assert slots[day][0] == "09:00"
        assert slots[day][-1] == "22:30"


def test_auto_redistributes_slots_when_max_daily_changes(db) -> None:
    pipe = make_pipeline("mxchange")
    make_source("mxchange")
    _enable_with_slots(pipe["id"], max_daily=3, slots=["11:00", "15:00", "19:00"])

    client = TestClient(create_app())
    response = client.put(
        f"/api/facebook/pipelines/{pipe['id']}/schedule",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        json={"enabled": True, "max_daily_publish": 10},
    )
    assert response.status_code == 200, response.text
    slots = response.json()["slots"]
    for day in WEEKDAY_NAMES:
        assert len(slots[day]) == 10, (day, slots[day])
        assert slots[day][0] == "11:00"
        assert slots[day][-1] == "19:00"


def test_put_without_slots_preserves_existing_slots(db) -> None:
    pipe = make_pipeline("mxpreserve")
    make_source("mxpreserve")
    client = TestClient(create_app())
    custom = {day: ["12:34"] for day in WEEKDAY_NAMES}
    created = client.put(
        f"/api/facebook/pipelines/{pipe['id']}/schedule",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        json={"enabled": True, "max_daily_publish": 5, "slots": custom},
    )
    assert created.status_code == 200, created.text

    updated = client.put(
        f"/api/facebook/pipelines/{pipe['id']}/schedule",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        json={"enabled": True, "max_daily_publish": 5},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["slots"] == custom


def test_max_daily_rejects_invalid_values(db) -> None:
    pipe = make_pipeline("mxinvalid")
    make_source("mxinvalid")
    client = TestClient(create_app())
    for value in (0, -1, 1001):
        response = client.put(
            f"/api/facebook/pipelines/{pipe['id']}/schedule",
            headers={**AUTH_HEADERS, "Content-Type": "application/json"},
            json={"enabled": True, "max_daily_publish": value},
        )
        assert response.status_code == 422, (value, response.text)


@pytest.mark.parametrize("max_daily", [10, 20])
def test_scheduler_enqueues_above_five(db, max_daily: int) -> None:
    suffix = f"mxq{max_daily}"
    pipe = make_pipeline(suffix)
    src = make_source(suffix)
    dest = make_destination(suffix)
    slots = _slots(max_daily)
    _enable_with_slots(pipe["id"], max_daily=max_daily, slots=slots)

    for index in range(max_daily):
        seed_reel(src["id"], f"r{index}")
        _mark_ai_ready(pipe["id"], f"{src['id']}_r{index}")

    now = _at(2, 0)
    result = asyncio.run(
        execute_daily_batch(pipe["id"], dest["id"], force_now=True, now=now)
    )
    assert result["videos_enqueued"] == max_daily, result
    assert [slot["slot"] for slot in result["slots"]] == slots
    assert result["daily_limit"] == max_daily
    assert result["slot_capacity"] == max_daily
    assert result["capacity_limited"] is False

    stats = asyncio.run(publish_queue.get_queue_stats())
    assert stats["queued"] == max_daily, stats

    # A second manual run must not double-book or exceed max.
    again = asyncio.run(
        execute_daily_batch(pipe["id"], dest["id"], force_now=True, now=now)
    )
    assert again["videos_enqueued"] == max_daily, again
    assert again["reason"] == "BATCH_ALREADY_COMPLETED", again
    stats_again = asyncio.run(publish_queue.get_queue_stats())
    assert stats_again["queued"] == max_daily, stats_again

    status = asyncio.run(describe_schedule_status(pipe["id"], now=now))
    assert status is not None
    assert status["daily_limit"] == max_daily
    assert status["slots_today"] == max_daily
    assert status["committed_today"] == max_daily
    assert status["published_today"] == 0
    assert status["remaining_today"] == 0
    assert status["scheduler_state"] == "daily_limit_reached"
    assert status["next_publish_at"] is not None


def test_capacity_warning_when_slots_are_too_few(db) -> None:
    pipe = make_pipeline("mxcap")
    src = make_source("mxcap")
    dest = make_destination("mxcap")
    _enable_with_slots(pipe["id"], max_daily=10, slots=["03:00", "04:00"])
    seed_reel(src["id"], "r1")

    result = asyncio.run(
        execute_daily_batch(pipe["id"], dest["id"], force_now=True, now=_at(2, 0))
    )
    assert result["daily_limit"] == 10, result
    assert result["slot_capacity"] == 2, result
    assert result["capacity_limited"] is True, result
    assert "Max videos/day = 10" in (result["warning"] or "")

    status = asyncio.run(describe_schedule_status(pipe["id"], now=_at(2, 0)))
    assert status is not None
    assert status["feasible_today"] == 2
    assert status["capacity_warning"]


def test_quota_pause_blocks_scheduler_then_recovers(db) -> None:
    pipe = make_pipeline("mxquota")
    src = make_source("mxquota")
    dest = make_destination("mxquota")
    _enable_with_slots(pipe["id"], max_daily=5, slots=_slots(5))
    seed_reel(src["id"], "r1")
    _mark_ai_ready(pipe["id"], f"{src['id']}_r1")

    now = _at(2, 0)
    asyncio.run(
        quota.pause_pipeline(
            pipe["id"], minutes=60, reason="YOUTUBE_QUOTA_EXCEEDED", now=now
        )
    )
    assert asyncio.run(quota.get_active_pause(pipe["id"], now=now)) is not None

    blocked = asyncio.run(
        execute_daily_batch(pipe["id"], dest["id"], force_now=True, now=now)
    )
    assert blocked["videos_enqueued"] == 0, blocked
    assert blocked["reason"] == "QUOTA_PAUSED", blocked

    status = asyncio.run(describe_schedule_status(pipe["id"], now=now))
    assert status is not None
    assert status["scheduler_state"] == "quota_paused"
    assert status["quota_paused_until"] is not None
    assert status["quota_pause_reason"] == "YOUTUBE_QUOTA_EXCEEDED"

    recovered = asyncio.run(
        execute_daily_batch(pipe["id"], dest["id"], force_now=True, now=_at(3, 1))
    )
    assert recovered["videos_enqueued"] == 1, recovered
    assert recovered["reason"] is None, recovered


def test_quota_pause_excludes_pipeline_from_queue_claim(db) -> None:
    pipe = make_pipeline("mxclaim")
    make_source("mxclaim")
    now = datetime.now(timezone.utc)
    asyncio.run(quota.pause_pipeline(pipe["id"], minutes=60, now=now))

    queue_id = asyncio.run(
        publish_queue.enqueue_publish_job(
            pipeline_id=pipe["id"],
            destination_id="dest_claim",
            reel_db_id="reel_claim",
            publication_id="pub_claim",
        )
    )
    assert asyncio.run(publish_queue.claim_next_job(worker_id="w1")) is None

    asyncio.run(quota.clear_pause(pipe["id"]))
    claimed = asyncio.run(publish_queue.claim_next_job(worker_id="w1"))
    assert claimed is not None
    assert claimed["id"] == queue_id


def test_publisher_quota_pause_requeues_job(db) -> None:
    pipe = make_pipeline("mxpause")
    make_source("mxpause")
    queue_id = asyncio.run(
        publish_queue.enqueue_publish_job(
            pipeline_id=pipe["id"],
            destination_id="dest_pause",
            reel_db_id="reel_pause",
            publication_id="pub_pause",
        )
    )

    result = asyncio.run(
        _pause_for_quota(
            queue_id,
            "pub_pause",
            None,
            Path("/tmp/non-existent"),
            0.0,
            "quota exceeded",
            pipeline_id=pipe["id"],
        )
    )
    assert result["result"] == "quota_paused", result
    assert result["error_code"] == "YOUTUBE_QUOTA_EXCEEDED", result

    job = asyncio.run(publish_queue.get_job(queue_id))
    assert job is not None
    assert job["status"] == "queued", job
    assert job["stage"] == "quota_paused", job
    assert asyncio.run(quota.get_active_pause(pipe["id"])) is not None
