from typing import Any

from ...db.client import execute, result_to_dict, result_to_dicts


async def enqueue_publication_job(
    job_id: str,
    pipeline_id: str,
    destination_id: str,
    reel_db_id: str,
    publication_id: str,
    priority: int = 0,
    stage: str | None = None,
) -> dict[str, Any]:
    await execute(
        """
        INSERT INTO tiktok_publish_queue
            (id, pipeline_id, destination_id, reel_db_id, publication_id,
             priority, stage, status)
        VALUES
            (:id, :pipeline_id, :destination_id, :reel_db_id, :publication_id,
             :priority, :stage, 'queued')
        """,
        {
            "id": job_id,
            "pipeline_id": pipeline_id,
            "destination_id": destination_id,
            "reel_db_id": reel_db_id,
            "publication_id": publication_id,
            "priority": priority,
            "stage": stage,
        },
    )
    res = await execute(
        """
        SELECT id, pipeline_id, destination_id, reel_db_id, publication_id,
               status, priority, stage, error_code, error,
               queued_at, started_at, finished_at, created_at, updated_at
        FROM tiktok_publish_queue WHERE id = :id
        """,
        {"id": job_id},
    )
    return result_to_dict(res)


async def claim_next_job(worker_id: str) -> dict[str, Any] | None:
    """Atomically claim the highest-priority queued job."""
    now = _now()
    res = await execute(
        """
        UPDATE tiktok_publish_queue
        SET status = 'processing', started_at = :now,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = (
            SELECT id FROM tiktok_publish_queue
            WHERE status = 'queued'
            ORDER BY priority DESC, queued_at ASC, id ASC
            LIMIT 1
        )
        RETURNING id, pipeline_id, destination_id, reel_db_id, publication_id,
           status, priority, stage, error_code, error,
           queued_at, started_at, finished_at, created_at, updated_at
        """,
        {"now": now},
    )
    if res.rows:
        row = result_to_dict(res)
        row["worker_id"] = worker_id
        return row
    return None


async def mark_job_stage(job_id: str, stage: str | None, error_code: str | None = None, error: str | None = None) -> None:
    updates = ["updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"]
    params: dict[str, Any] = {"id": job_id, "stage": stage, "err_code": error_code, "err": error}
    if stage is not None:
        updates.append("stage = :stage")
    if error_code is not None:
        updates.append("error_code = :err_code")
    if error is not None:
        updates.append("error = :err")
    await execute(
        f"UPDATE tiktok_publish_queue SET {', '.join(updates)} WHERE id = :id",
        params,
    )


async def complete_job(job_id: str, status: str = "done", error: str | None = None) -> None:
    await execute(
        """
        UPDATE tiktok_publish_queue
        SET status = :status, finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
            error = :error
        WHERE id = :id
        """,
        {"id": job_id, "status": status, "error": error},
    )


async def release_job(job_id: str, error: str | None = None) -> None:
    await execute(
        """
        UPDATE tiktok_publish_queue
        SET status = 'queued', started_at = NULL,
            error = :error, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = :id
        """,
        {"id": job_id, "error": error},
    )


def _now() -> str:
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
