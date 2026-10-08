"""Processing jobs repo: atomic claim/lease, progress, snapshots."""

from __future__ import annotations

import json
from typing import Any

from app.db.client import get_client
from app.db.repositories import new_id, now_iso

ACTIVE = ("queued", "running")


def create_job(pipeline_id: str, *, inventory_id: str | None = None,
               manual_url: str | None = None,
               mode: str = "auto") -> dict[str, Any]:
    jid = new_id("ajob")
    client = get_client()
    client.execute(
        "INSERT INTO audio_processing_jobs (id, pipeline_id, inventory_id, "
        "manual_url, mode, status, stage) VALUES (?, ?, ?, ?, ?, 'queued', 'queued')",
        (jid, pipeline_id, inventory_id, manual_url, mode))
    client.commit()
    row = get_job(jid)
    assert row is not None
    return row


def get_job(job_id: str) -> dict[str, Any] | None:
    row = get_client().execute(
        "SELECT * FROM audio_processing_jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_jobs(pipeline_id: str, limit: int = 50) -> list[dict[str, Any]]:
    return [dict(r) for r in get_client().execute(
        "SELECT * FROM audio_processing_jobs WHERE pipeline_id = ? "
        "ORDER BY created_at DESC LIMIT ?", (pipeline_id, limit)).fetchall()]


def claim_next_queued(worker_id: str, lease_seconds: int = 3600) -> dict | None:
    """Single-worker claim: oldest queued job. Lease prevents double-run."""
    from datetime import datetime, timedelta, timezone

    client = get_client()
    row = client.execute(
        "SELECT * FROM audio_processing_jobs WHERE status = 'queued' "
        "ORDER BY created_at ASC LIMIT 1").fetchone()
    if row is None:
        return None
    lease_until = (datetime.now(timezone.utc)
                   + timedelta(seconds=lease_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
    client.execute(
        "UPDATE audio_processing_jobs SET status = 'running', stage = 'claimed', "
        "lease_owner = ?, lease_expires_at = ?, run_at = ?, updated_at = ? "
        "WHERE id = ? AND status = 'queued'",
        (worker_id, lease_until, now_iso(), now_iso(), row["id"]))
    client.commit()
    fresh = get_job(row["id"])
    if fresh and fresh["status"] == "running" and fresh.get("lease_owner") == worker_id:
        return fresh
    return None


def update_job(job_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {"status", "stage", "progress_percent", "background_asset_id",
               "logo_asset_id", "template_asset_id", "srt_object_key", "ai_title", "ai_description",
               "ai_hashtags_json", "ai_metadata_status", "youtube_video_id",
               "youtube_url", "last_error_code", "last_error_message",
               "lease_owner", "lease_expires_at"}
    sets, params = [], []
    for key, value in fields.items():
        if key in allowed:
            sets.append(f"{key} = ?")
            params.append(value)
    if not sets:
        return get_job(job_id)
    sets.append("updated_at = ?")
    params.extend([now_iso(), job_id])
    client = get_client()
    client.execute(f"UPDATE audio_processing_jobs SET {', '.join(sets)} WHERE id = ?",
                   params)
    client.commit()
    return get_job(job_id)


def add_event(job_id: str, stage: str, state: str,
              detail: str | None = None) -> None:
    client = get_client()
    client.execute(
        "INSERT INTO audio_job_events (job_id, stage, state, detail) "
        "VALUES (?, ?, ?, ?)", (job_id, stage, state, detail))
    client.commit()


def job_events(job_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in get_client().execute(
        "SELECT * FROM audio_job_events WHERE job_id = ? ORDER BY created_at",
        (job_id,)).fetchall()]


def recover_stale_running(lease_grace_seconds: int = 900) -> int:
    """Jobs stuck running past lease expiry (e.g. restart) go back to queued."""
    client = get_client()
    # lease check done in python for portability
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    count = 0
    for r in client.execute(
            "SELECT id, lease_expires_at FROM audio_processing_jobs "
            "WHERE status = 'running'").fetchall():
        if not r["lease_expires_at"] or r["lease_expires_at"] < now:
            client.execute(
                "UPDATE audio_processing_jobs SET status = 'queued', stage = 'requeued', "
                "lease_owner = NULL, lease_expires_at = NULL, updated_at = ? WHERE id = ?",
                (now_iso(), r["id"]))
            count += 1
    client.commit()
    return count
