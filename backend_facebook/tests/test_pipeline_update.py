"""Pipeline flags update (enabled / auto_publish) and the scheduler auto gate.

- PATCH /api/facebook/pipelines/{id} updates only provided fields.
- Automatic scheduler ticks never enqueue when auto_publish=false.
- Manual force_now batches still run (explicit user action).
"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.db.repositories import pipelines, schedules
from app.main import create_app
from app.services.facebook_scheduler import describe_schedule_status, execute_daily_batch
from tests.test_manual_batch import _at, _enable, _mark_ai_ready  # noqa: F401
from tests.test_scheduler import (  # noqa: F401  (module-local db fixture)
    AUTH_HEADERS,
    db,
    make_destination,
    make_pipeline,
    make_source,
    seed_reel,
)


def _set_flags(pipeline_id: str, **flags) -> dict | None:
    async def _run():
        return await pipelines.update_pipeline(pipeline_id, **flags)

    return asyncio.run(_run())


# ---------- repo: partial update ----------


def test_update_auto_publish_only_preserves_name_slug(db) -> None:
    pipe = make_pipeline("u1")
    assert pipe["auto_publish"] is True

    updated = _set_flags(pipe["id"], auto_publish=False)

    assert updated is not None
    assert updated["auto_publish"] is False
    assert updated["enabled"] is True
    assert updated["name"] == pipe["name"]
    assert updated["slug"] == pipe["slug"]


def test_update_enabled_only_preserves_auto_publish(db) -> None:
    pipe = make_pipeline("u2")

    updated = _set_flags(pipe["id"], enabled=False)

    assert updated is not None
    assert updated["enabled"] is False
    assert updated["auto_publish"] is True


def test_update_missing_pipeline_returns_none(db) -> None:
    assert _set_flags("pl_does_not_exist", auto_publish=True) is None


# ---------- route: PATCH ----------


def test_patch_route_persists_auto_publish(db) -> None:
    pipe = make_pipeline("u3")
    client = TestClient(create_app())

    r = client.patch(
        f"/api/facebook/pipelines/{pipe['id']}",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        json={"auto_publish": False},
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["auto_publish"] is False
    assert body["name"] == pipe["name"]
    assert body["slug"] == pipe["slug"]
    # Reload proves persistence.
    reloaded = asyncio.run(pipelines.get_pipeline(pipe["id"]))
    assert reloaded is not None and reloaded["auto_publish"] is False


def test_patch_route_404_for_missing_pipeline(db) -> None:
    client = TestClient(create_app())
    r = client.patch(
        "/api/facebook/pipelines/pl_does_not_exist",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        json={"auto_publish": True},
    )
    assert r.status_code == 404, r.text


def test_patch_route_400_for_empty_body(db) -> None:
    pipe = make_pipeline("u4")
    client = TestClient(create_app())
    r = client.patch(
        f"/api/facebook/pipelines/{pipe['id']}",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        json={},
    )
    assert r.status_code == 400, r.text


# ---------- scheduler: auto gate ----------


def test_auto_tick_blocked_when_auto_publish_off(db) -> None:
    pipe, src, dest = _enable("u5")
    seed_reel(src["id"], "r1")
    _mark_ai_ready(pipe["id"], f"{src['id']}_r1")
    _set_flags(pipe["id"], auto_publish=False)

    result = asyncio.run(
        execute_daily_batch(pipe["id"], dest["id"], force_now=False, now=_at(12, 0))
    )

    assert result["videos_enqueued"] == 0, result
    assert result["reason"] == "AUTO_PUBLISH_DISABLED", result
    # Daily batch row must not be burned by the blocked automatic tick.
    existing = asyncio.run(
        schedules.get_batch(pipe["id"], dest["id"], "2026-10-05")
    )
    assert existing is None


def test_manual_run_still_works_when_auto_publish_off(db) -> None:
    pipe, src, dest = _enable("u6")
    seed_reel(src["id"], "r1")
    _mark_ai_ready(pipe["id"], f"{src['id']}_r1")
    _set_flags(pipe["id"], auto_publish=False)

    result = asyncio.run(
        execute_daily_batch(pipe["id"], dest["id"], force_now=True, now=_at(12, 0))
    )

    assert result["videos_enqueued"] == 1, result
    assert result["reason"] is None


def test_auto_tick_runs_when_auto_publish_on(db) -> None:
    pipe, src, dest = _enable("u7")
    seed_reel(src["id"], "r1")
    _mark_ai_ready(pipe["id"], f"{src['id']}_r1")

    result = asyncio.run(
        execute_daily_batch(pipe["id"], dest["id"], force_now=False, now=_at(12, 0))
    )

    assert result["reason"] != "AUTO_PUBLISH_DISABLED", result
    assert result["videos_enqueued"] == 1, result


# ---------- schedule/status: additive batch + queue detail ----------


def test_schedule_status_exposes_batch_and_queue_counts(db) -> None:
    pipe, src, dest = _enable("st")
    seed_reel(src["id"], "r1")
    _mark_ai_ready(pipe["id"], f"{src['id']}_r1")
    result = asyncio.run(
        execute_daily_batch(pipe["id"], dest["id"], force_now=True, now=_at(12, 0))
    )
    assert result["videos_enqueued"] == 1, result

    status = asyncio.run(describe_schedule_status(pipe["id"], now=_at(12, 0)))

    for key in (
        "inventory_total", "ai_generated", "ai_pending", "ai_failed", "ai_ready",
        "queue_queued", "queue_processing",
        "batch_planned", "batch_uploaded", "batch_failed",
    ):
        assert key in status, key
    assert status["inventory_total"] == 1
    assert status["ai_ready"] == 0  # the ready reel was claimed into queued
    assert status["batch_planned"] == 4  # planned counts slots, not videos
    assert status["batch_uploaded"] == 1
    assert status["batch_failed"] == 3  # 3 slots left with no reel to claim
    assert status["queue_queued"] == 1


# ---------- rename ----------


def test_rename_preserves_slug_and_flags(db) -> None:
    pipe = make_pipeline("rn1")

    updated = _set_flags(pipe["id"], name="CHÀNG HIU VLOG")

    assert updated is not None
    assert updated["name"] == "CHÀNG HIU VLOG"
    assert updated["slug"] == pipe["slug"]
    assert updated["enabled"] is True
    assert updated["auto_publish"] is True


def test_rename_rejects_empty_name(db) -> None:
    import pytest

    pipe = make_pipeline("rn2")
    with pytest.raises(ValueError):
        asyncio.run(pipelines.update_pipeline(pipe["id"], name="   "))


def test_patch_route_renames_pipeline(db) -> None:
    pipe = make_pipeline("rn3")
    client = TestClient(create_app())
    r = client.patch(
        f"/api/facebook/pipelines/{pipe['id']}",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        json={"name": "CHÀNG HIU VLOG"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "CHÀNG HIU VLOG"
    assert body["slug"] == pipe["slug"]
    reloaded = asyncio.run(pipelines.get_pipeline(pipe["id"]))
    assert reloaded is not None and reloaded["name"] == "CHÀNG HIU VLOG"


def test_patch_route_400_for_blank_name(db) -> None:
    pipe = make_pipeline("rn4")
    client = TestClient(create_app())
    r = client.patch(
        f"/api/facebook/pipelines/{pipe['id']}",
        headers={**AUTH_HEADERS, "Content-Type": "application/json"},
        json={"name": "   "},
    )
    assert r.status_code == 400, r.text


def test_schedule_status_exposes_full_queue_counts(db) -> None:
    status = asyncio.run(describe_schedule_status("pl_does_not_exist", now=_at(12, 0)))
    assert status is None
    pipe, src, dest = _enable("st2")
    status = asyncio.run(describe_schedule_status(pipe["id"], now=_at(12, 0)))
    for key in ("queue_queued", "queue_processing", "queue_scheduled", "queue_failed", "queue_total"):
        assert key in status, key
        assert status[key] == 0


# ---------- manual top-up of a completed batch ----------

MONDAY_SLOTS = {0: ["11:30", "14:30", "18:30", "20:30", "22:30"]}


def _ready(pipe_id: str, src_id: str, rid: str) -> str:
    from tests.test_scheduler import seed_reel as _seed

    _seed(src_id, rid)
    reel_db_id = f"{src_id}_{rid}"
    _mark_ai_ready(pipe_id, reel_db_id)
    return reel_db_id


def test_manual_top_up_completed_batch(db) -> None:
    pipe, src, dest = _enable("tp1", slots=MONDAY_SLOTS)
    _ready(pipe["id"], src["id"], "r1")

    first = asyncio.run(
        execute_daily_batch(pipe["id"], dest["id"], force_now=True, now=_at(12, 0))
    )
    assert first["videos_enqueued"] == 1, first
    assert first["reason"] is None

    _ready(pipe["id"], src["id"], "r2")
    _ready(pipe["id"], src["id"], "r3")
    second = asyncio.run(
        execute_daily_batch(pipe["id"], dest["id"], force_now=True, now=_at(12, 1))
    )

    # 14:30 taken by the first run; 18:30/20:30/22:30 free; quota 5-1=4.
    assert second["videos_enqueued"] == 2, second
    assert second["reason"] is None

    status = asyncio.run(describe_schedule_status(pipe["id"], now=_at(12, 1)))
    assert status["batch_uploaded"] == 3
    assert status["scheduled_today"] == 3


def test_manual_top_up_never_double_books_a_slot(db) -> None:
    from app.db.repositories import publications as publications_repo

    pipe, src, dest = _enable("tp2", slots=MONDAY_SLOTS)
    for rid in ("r1", "r2", "r3", "r4"):
        _ready(pipe["id"], src["id"], rid)

    asyncio.run(
        execute_daily_batch(pipe["id"], dest["id"], force_now=True, now=_at(12, 0))
    )
    # 4 reels take all 4 future slots; second run finds nothing free.
    again = asyncio.run(
        execute_daily_batch(pipe["id"], dest["id"], force_now=True, now=_at(12, 5))
    )
    assert again["reason"] == "BATCH_ALREADY_COMPLETED", again
    assert again["videos_enqueued"] == 4, again

    used = asyncio.run(
        publications_repo.used_slot_times_for_date(pipe["id"], "2026-10-05")
    )
    assert used == ["14:30", "18:30", "20:30", "22:30"], used


def test_auto_tick_never_tops_up_completed_batch(db) -> None:
    from app.services.facebook_scheduler import run_scheduler_tick

    pipe, src, dest = _enable("tp3", slots=MONDAY_SLOTS)
    _ready(pipe["id"], src["id"], "r1")
    asyncio.run(
        execute_daily_batch(pipe["id"], dest["id"], force_now=True, now=_at(12, 0))
    )

    # The automatic tick must not add anything on top of a completed batch.
    # (Its response echoes the already-enqueued count; the source of truth
    # is the batch row, which must stay at 1.)
    asyncio.run(run_scheduler_tick(now=_at(12, 30)))
    status = asyncio.run(describe_schedule_status(pipe["id"], now=_at(12, 30)))
    assert status["batch_uploaded"] == 1
    assert status["batch_status"] == "completed"
