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
from app.services.facebook_scheduler import execute_daily_batch
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
