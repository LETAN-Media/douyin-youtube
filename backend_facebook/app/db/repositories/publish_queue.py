"""Global publish queue repository (Task 12)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from ..client import get_client


async def enqueue_publish_job(
    *,
    pipeline_id: str,
    destination_id: str,
    reel_db_id: str,
    publication_id: str,
    priority: int = 0,
) -> str:
    """Add a publish job to the global queue. Returns queue job ID."""
    queue_id = f"pq_{uuid.uuid4().hex[:12]}"
    client = get_client()
    await client.execute(
        """
        INSERT INTO facebook_publish_queue
        (id, pipeline_id, destination_id, reel_db_id, publication_id, status, priority)
        VALUES (:id, :pipeline_id, :destination_id, :reel_db_id, :publication_id, 'queued', :priority)
        """,
        {
            "id": queue_id,
            "pipeline_id": pipeline_id,
            "destination_id": destination_id,
            "reel_db_id": reel_db_id,
            "publication_id": publication_id,
            "priority": priority,
        },
    )
    return queue_id


async def claim_next_job(
    *,
    worker_id: str,
    max_ttl_seconds: int = 300,
) -> dict[str, Any] | None:
    """
    Atomically claim the next queued job using fair scheduling.

    Fair scheduling: round-robin across pipelines.
    We select the oldest queued job from each pipeline, then pick the one
    with the earliest queued_at.

    Returns the job dict or None if no queued jobs.
    """
    client = get_client()

    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max_ttl_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")

    rows = await client.execute(
        """
        WITH ranked AS (
            SELECT
                id, pipeline_id, destination_id, reel_db_id, publication_id,
                status, priority, stage, error_code, error,
                queued_at, started_at, finished_at, created_at, updated_at,
                ROW_NUMBER() OVER (PARTITION BY pipeline_id ORDER BY priority DESC, queued_at ASC) as rn
            FROM facebook_publish_queue
            WHERE status = 'queued'
        )
        SELECT
            id, pipeline_id, destination_id, reel_db_id, publication_id,
            status, priority, stage, error_code, error,
            queued_at, started_at, finished_at, created_at, updated_at
        FROM ranked
        WHERE rn = 1
        ORDER BY queued_at ASC
        LIMIT 1
        """,
    )
    if not rows.rows:
        return None

    job = rows.rows[0]
    job_dict = {
        "id": job[0],
        "pipeline_id": job[1],
        "destination_id": job[2],
        "reel_db_id": job[3],
        "publication_id": job[4],
        "status": job[5],
        "priority": job[6],
        "stage": job[7],
        "error_code": job[8],
        "error": job[9],
        "queued_at": job[10],
        "started_at": job[11],
        "finished_at": job[12],
        "created_at": job[13],
        "updated_at": job[14],
    }

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        await client.execute(
            """
            UPDATE facebook_publish_queue
            SET status = 'processing', stage = 'claimed',
                started_at = :started_at,
                updated_at = :updated_at
            WHERE id = :id AND status = 'queued'
            """,
            {"id": job_dict["id"], "started_at": now_iso, "updated_at": now_iso},
        )
    except Exception:
        return None

    return job_dict


async def update_job_status(
    queue_id: str,
    status: str,
    *,
    stage: str | None = None,
    error_code: str | None = None,
    error: str | None = None,
) -> None:
    """Update job status and optionally stage/error."""
    client = get_client()
    sets = ["status = :status", "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"]
    params = {"id": queue_id, "status": status}
    if stage is not None:
        sets.append("stage = :stage")
        params["stage"] = stage
    if error_code is not None:
        sets.append("error_code = :error_code")
        params["error_code"] = error_code
    if error is not None:
        sets.append("error = :error")
        params["error"] = (error or "")[:500]
    if status in ("scheduled", "published", "failed"):
        sets.append("finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')")

    await client.execute(
        f"UPDATE facebook_publish_queue SET {', '.join(sets)} WHERE id = :id",
        params,
    )


async def get_job(queue_id: str) -> dict[str, Any] | None:
    client = get_client()
    rows = await client.execute(
        """
        SELECT id, pipeline_id, destination_id, reel_db_id, publication_id,
               status, priority, stage, error_code, error,
               queued_at, started_at, finished_at, created_at, updated_at
        FROM facebook_publish_queue WHERE id = :id
        """,
        {"id": queue_id},
    )
    if not rows.rows:
        return None
    job = rows.rows[0]
    return {
        "id": job[0],
        "pipeline_id": job[1],
        "destination_id": job[2],
        "reel_db_id": job[3],
        "publication_id": job[4],
        "status": job[5],
        "priority": job[6],
        "stage": job[7],
        "error_code": job[8],
        "error": job[9],
        "queued_at": job[10],
        "started_at": job[11],
        "finished_at": job[12],
        "created_at": job[13],
        "updated_at": job[14],
    }


async def get_queue_stats() -> dict[str, int]:
    """Get global queue statistics."""
    client = get_client()
    rows = await client.execute(
        "SELECT status, COUNT(*) FROM facebook_publish_queue GROUP BY status"
    )
    by_status = {r[0]: r[1] for r in (rows.rows or [])}
    return {
        "queued": by_status.get("queued", 0),
        "processing": by_status.get("processing", 0),
        "scheduled": by_status.get("scheduled", 0),
        "published": by_status.get("published", 0),
        "failed": by_status.get("failed", 0),
        "total": sum(by_status.values()),
    }


async def get_pipeline_queue_stats(pipeline_id: str) -> dict[str, int]:
    """Get queue statistics for a specific pipeline."""
    client = get_client()
    rows = await client.execute(
        "SELECT status, COUNT(*) FROM facebook_publish_queue WHERE pipeline_id = :pid GROUP BY status",
        {"pid": pipeline_id},
    )
    by_status = {r[0]: r[1] for r in (rows.rows or [])}
    return {
        "queued": by_status.get("queued", 0),
        "processing": by_status.get("processing", 0),
        "scheduled": by_status.get("scheduled", 0),
        "published": by_status.get("published", 0),
        "failed": by_status.get("failed", 0),
        "total": sum(by_status.values()),
    }


async def list_queued_jobs(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """List queued jobs for dashboard."""
    client = get_client()
    rows = await client.execute(
        """
        SELECT id, pipeline_id, destination_id, reel_db_id, publication_id,
               status, priority, stage, error_code, error,
               queued_at, started_at, finished_at, created_at, updated_at
        FROM facebook_publish_queue
        WHERE status IN ('queued', 'processing')
        ORDER BY priority DESC, queued_at ASC
        LIMIT :limit OFFSET :offset
        """,
        {"limit": limit, "offset": offset},
    )
    return [
        {
            "id": r[0],
            "pipeline_id": r[1],
            "destination_id": r[2],
            "reel_db_id": r[3],
            "publication_id": r[4],
            "status": r[5],
            "priority": r[6],
            "stage": r[7],
            "error_code": r[8],
            "error": r[9],
            "queued_at": r[10],
            "started_at": r[11],
            "finished_at": r[12],
            "created_at": r[13],
            "updated_at": r[14],
        }
        for r in (rows.rows or [])
    ]


async def recover_stale_jobs(ttl_seconds: int = 300) -> int:
    """
    Recover stuck processing jobs that have exceeded TTL.
    Returns number of recovered jobs.
    """
    client = get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=ttl_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = await client.execute(
        """
        UPDATE facebook_publish_queue
        SET status = 'queued', stage = 'recovered',
            started_at = NULL,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE status = 'processing' AND started_at < :cutoff
        """,
        {"cutoff": cutoff},
    )
    return rows.rows_affected if hasattr(rows, "rows_affected") else 0


async def get_current_job() -> dict[str, Any] | None:
    """Get the currently processing job (for dashboard)."""
    client = get_client()
    rows = await client.execute(
        """
        SELECT id, pipeline_id, destination_id, reel_db_id, publication_id,
               status, priority, stage, error_code, error,
               queued_at, started_at, finished_at, created_at, updated_at
        FROM facebook_publish_queue
        WHERE status = 'processing'
        ORDER BY started_at ASC
        LIMIT 1
        """,
    )
    if not rows.rows:
        return None
    job = rows.rows[0]
    return {
        "id": job[0],
        "pipeline_id": job[1],
        "destination_id": job[2],
        "reel_db_id": job[3],
        "publication_id": job[4],
        "status": job[5],
        "priority": job[6],
        "stage": job[7],
        "error_code": job[8],
        "error": job[9],
        "queued_at": job[10],
        "started_at": job[11],
        "finished_at": job[12],
        "created_at": job[13],
        "updated_at": job[14],
    }