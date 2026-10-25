"""DELETE /api/facebook/pipelines/{id}: confirmation endpoint semantics.

Covers the full dependent-data cascade, protection for in-flight work, auth
and 404, and isolation from other pipelines. Tests use the local /tmp DB.
"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.db.client import get_client
from app.db.repositories import publications
from app.main import create_app
from tests.test_scheduler import (  # noqa: F401  (module-local db fixture)
    AUTH_HEADERS,
    db,
    make_destination,
    make_pipeline,
    make_source,
    seed_reel,
)


async def _exec(sql: str, params: dict | None = None) -> None:
    await get_client().execute(sql, params)


def _seed_dependents(pipe: dict, src: dict, dest: dict) -> dict[str, str]:
    """Insert one row in every pipeline-scoped table."""
    ids = {
        "reel_db_id": f"{src['id']}_r1",
        "publication_id": f"pub_{pipe['id']}",
        "schedule_id": f"sch_{pipe['id']}",
        "slot_id": f"slot_{pipe['id']}",
        "run_id": f"run_{pipe['id']}",
        "batch_id": f"batch_{pipe['id']}",
        "queue_id": f"q_{pipe['id']}",
        "manual_id": f"m_{pipe['id']}",
        "scan_id": f"scan_{pipe['id']}",
        "oauth_state": f"state_{pipe['id']}",
    }
    seed_reel(src["id"], "r1")

    async def _run() -> None:
        await publications.get_or_create(
            publication_id=ids["publication_id"],
            reel_db_id=ids["reel_db_id"],
            destination_id=dest["id"],
        )
        await _exec(
            "INSERT INTO facebook_ai_metadata (reel_db_id, title, status) "
            "VALUES (:rid, 'T', 'generated')",
            {"rid": ids["reel_db_id"]},
        )
        await _exec(
            "INSERT INTO facebook_publish_schedules (id, pipeline_id) "
            "VALUES (:id, :pid)",
            {"id": ids["schedule_id"], "pid": pipe["id"]},
        )
        await _exec(
            "INSERT INTO facebook_publish_schedule_slots "
            "(id, schedule_id, weekday, slot_time) VALUES (:id, :sid, 0, '09:00')",
            {"id": ids["slot_id"], "sid": ids["schedule_id"]},
        )
        await _exec(
            "INSERT INTO facebook_scheduler_runs "
            "(id, pipeline_id, destination_id, scheduled_for) "
            "VALUES (:id, :pid, :did, '2026-10-05T02:00:00Z')",
            {"id": ids["run_id"], "pid": pipe["id"], "did": dest["id"]},
        )
        await _exec(
            "INSERT INTO facebook_scheduler_batches "
            "(id, pipeline_id, destination_id, local_date, scheduled_batch_time) "
            "VALUES (:id, :pid, :did, '2026-10-05', '06:00')",
            {"id": ids["batch_id"], "pid": pipe["id"], "did": dest["id"]},
        )
        await _exec(
            "INSERT INTO facebook_ai_settings (pipeline_id) VALUES (:pid)",
            {"pid": pipe["id"]},
        )
        await _exec(
            "INSERT INTO facebook_publish_queue "
            "(id, pipeline_id, destination_id, reel_db_id, publication_id, status) "
            "VALUES (:id, :pid, :did, :rid, :pub, 'queued')",
            {
                "id": ids["queue_id"],
                "pid": pipe["id"],
                "did": dest["id"],
                "rid": ids["reel_db_id"],
                "pub": ids["publication_id"],
            },
        )
        await _exec(
            "INSERT INTO facebook_manual_publications "
            "(id, destination_id, pipeline_id, source_url, source_hash, status) "
            "VALUES (:id, :did, :pid, 'https://example.com/reel', 'hash', 'queued')",
            {"id": ids["manual_id"], "did": dest["id"], "pid": pipe["id"]},
        )
        await _exec(
            "INSERT INTO facebook_quota_pauses (pipeline_id, paused_until) "
            "VALUES (:pid, '2030-01-01T00:00:00Z')",
            {"pid": pipe["id"]},
        )
        await _exec(
            "INSERT INTO youtube_oauth_states "
            "(state, destination_id, pipeline_id, expires_at) "
            "VALUES (:state, :did, :pid, '2030-01-01T00:00:00Z')",
            {
                "state": ids["oauth_state"],
                "did": dest["id"],
                "pid": pipe["id"],
            },
        )
        await _exec(
            "INSERT INTO youtube_credentials (destination_id, credentials_json) "
            "VALUES (:did, '{}')",
            {"did": dest["id"]},
        )
        await _exec(
            "INSERT INTO scan_runs (id, source_id, status) "
            "VALUES (:id, :sid, 'completed')",
            {"id": ids["scan_id"], "sid": src["id"]},
        )

    asyncio.run(_run())
    return ids


async def _count(table: str, where: str, params: dict) -> int:
    rows = await get_client().execute(
        f"SELECT COUNT(*) FROM {table} WHERE {where}", params
    )
    return int(rows.rows[0][0] or 0) if rows.rows else 0


def test_delete_pipeline_cascades_without_touching_others(db) -> None:
    pipe = make_pipeline("del1")
    src = make_source("del1")
    dest = make_destination("del1")
    ids = _seed_dependents(pipe, src, dest)

    other = make_pipeline("del2")
    other_src = make_source("del2")
    other_dest = make_destination("del2")
    other_ids = _seed_dependents(other, other_src, other_dest)

    client = TestClient(create_app())
    r = client.delete(
        f"/api/facebook/pipelines/{pipe['id']}", headers=AUTH_HEADERS
    )
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True

    checks = [
        ("facebook_pipelines", "id = :v", pipe["id"]),
        ("facebook_sources", "pipeline_id = :v", pipe["id"]),
        ("facebook_reels", "source_id = :v", src["id"]),
        ("publications", "reel_db_id = :v", ids["reel_db_id"]),
        ("facebook_ai_metadata", "reel_db_id = :v", ids["reel_db_id"]),
        ("facebook_publish_queue", "pipeline_id = :v", pipe["id"]),
        ("facebook_manual_publications", "pipeline_id = :v", pipe["id"]),
        ("facebook_publish_schedules", "pipeline_id = :v", pipe["id"]),
        ("facebook_publish_schedule_slots", "id = :v", ids["slot_id"]),
        ("facebook_scheduler_runs", "pipeline_id = :v", pipe["id"]),
        ("facebook_scheduler_batches", "pipeline_id = :v", pipe["id"]),
        ("facebook_ai_settings", "pipeline_id = :v", pipe["id"]),
        ("facebook_quota_pauses", "pipeline_id = :v", pipe["id"]),
        ("youtube_oauth_states", "state = :v", ids["oauth_state"]),
        ("youtube_credentials", "destination_id = :v", dest["id"]),
        ("scan_runs", "source_id = :v", src["id"]),
        ("youtube_destinations", "pipeline_id = :v", pipe["id"]),
    ]
    for table, where, value in checks:
        assert asyncio.run(_count(table, where, {"v": value})) == 0, table

    # The other pipeline and all its rows are untouched.
    assert asyncio.run(
        _count("facebook_pipelines", "id = :v", {"v": other["id"]})
    ) == 1
    assert asyncio.run(
        _count("facebook_sources", "id = :v", {"v": other_src["id"]})
    ) == 1
    assert asyncio.run(
        _count("facebook_reels", "id = :v", {"v": other_ids["reel_db_id"]})
    ) == 1
    assert asyncio.run(
        _count(
            "publications",
            "id = :v",
            {"v": other_ids["publication_id"]},
        )
    ) == 1
    assert asyncio.run(
        _count("youtube_destinations", "id = :v", {"v": other_dest["id"]})
    ) == 1


def test_delete_pipeline_refuses_while_work_is_processing(db) -> None:
    pipe = make_pipeline("del3")
    src = make_source("del3")
    dest = make_destination("del3")
    ids = _seed_dependents(pipe, src, dest)

    def _set(table: str, id_value: str, status: str) -> None:
        asyncio.run(
            _exec(
                f"UPDATE {table} SET status = :status WHERE id = :id",
                {"status": status, "id": id_value},
            )
        )

    client = TestClient(create_app())
    url = f"/api/facebook/pipelines/{pipe['id']}"

    _set("facebook_publish_queue", ids["queue_id"], "processing")
    r = client.delete(url, headers=AUTH_HEADERS)
    assert r.status_code == 409, r.text
    assert r.json()["error"] == "PIPELINE_BUSY"

    _set("facebook_publish_queue", ids["queue_id"], "failed")
    _set("facebook_manual_publications", ids["manual_id"], "processing")
    r = client.delete(url, headers=AUTH_HEADERS)
    assert r.status_code == 409, r.text

    _set("facebook_manual_publications", ids["manual_id"], "failed")
    _set("scan_runs", ids["scan_id"], "running")
    r = client.delete(url, headers=AUTH_HEADERS)
    assert r.status_code == 409, r.text

    _set("scan_runs", ids["scan_id"], "completed")
    r = client.delete(url, headers=AUTH_HEADERS)
    assert r.status_code == 200, r.text


def test_delete_pipeline_auth_and_404(db) -> None:
    pipe = make_pipeline("del4")
    client = TestClient(create_app())

    r = client.delete(f"/api/facebook/pipelines/{pipe['id']}")
    assert r.status_code == 401

    r = client.delete(
        "/api/facebook/pipelines/pl_missing", headers=AUTH_HEADERS
    )
    assert r.status_code == 404
    assert r.json()["error"] == "PIPELINE_NOT_FOUND"
