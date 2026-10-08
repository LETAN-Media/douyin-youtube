"""Durable scan-run state (DB-backed progress, resume cursors)."""

from __future__ import annotations

from typing import Any

from app.db.client import get_client
from app.db.repositories import new_id, now_iso

ACTIVE = ("queued", "running")


def create_run(source_id: str, pipeline_id: str, scan_mode: str) -> dict[str, Any]:
    rid = new_id("ascan")
    client = get_client()
    client.execute(
        "INSERT INTO audio_scan_runs (id, source_id, pipeline_id, scan_mode, status) "
        "VALUES (?, ?, ?, ?, 'queued')", (rid, source_id, pipeline_id, scan_mode))
    client.commit()
    row = get_run(rid)
    assert row is not None
    return row


def get_run(run_id: str) -> dict[str, Any] | None:
    row = get_client().execute(
        "SELECT * FROM audio_scan_runs WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def active_run_for_source(source_id: str) -> dict[str, Any] | None:
    row = get_client().execute(
        "SELECT * FROM audio_scan_runs WHERE source_id = ? AND status IN "
        "('queued','running') ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (source_id,)).fetchone()
    return dict(row) if row else None


def latest_run_for_source(source_id: str) -> dict[str, Any] | None:
    row = get_client().execute(
        "SELECT * FROM audio_scan_runs WHERE source_id = ? "
        "ORDER BY created_at DESC, rowid DESC LIMIT 1", (source_id,)).fetchone()
    return dict(row) if row else None


def list_runs_for_source(source_id: str, limit: int = 20) -> list[dict[str, Any]]:
    return [dict(r) for r in get_client().execute(
        "SELECT * FROM audio_scan_runs WHERE source_id = ? "
        "ORDER BY created_at DESC LIMIT ?", (source_id, limit)).fetchall()]


def update_run(run_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {"status", "next_cursor", "pages_fetched", "videos_discovered",
               "videos_added", "videos_existing", "provider_reported_total",
               "pagination_exhausted", "stop_reason", "last_error_code",
               "last_error_message", "started_at", "completed_at", "scan_mode"}
    sets, params = [], []
    for key, value in fields.items():
        if key in allowed:
            sets.append(f"{key} = ?")
            params.append(value)
    if not sets:
        return get_run(run_id)
    sets.append("updated_at = ?")
    params.extend([now_iso(), run_id])
    client = get_client()
    client.execute(f"UPDATE audio_scan_runs SET {', '.join(sets)} WHERE id = ?",
                   params)
    client.commit()
    return get_run(run_id)
