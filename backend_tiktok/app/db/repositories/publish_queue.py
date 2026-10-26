from typing import Any

from ...db.client import execute, result_to_dict, result_to_dicts

MANUAL_JOB_PRIORITY = 1000


async def enqueue_publication_job(
    job_id: str,
    pipeline_id: str,
    destination_id: str,
    reel_db_id: str,
    publication_id: str,
    priority: int = 0,
    stage: str | None = None,
    scheduled_at: str | None = None,
) -> dict[str, Any]:
    await execute(
        """
        INSERT INTO tiktok_publish_queue
            (id, pipeline_id, destination_id, reel_db_id, publication_id,
             priority, stage, status, scheduled_at)
        VALUES
            (:id, :pipeline_id, :destination_id, :reel_db_id, :publication_id,
             :priority, :stage, 'queued', :scheduled_at)
        """,
        {
            "id": job_id,
            "pipeline_id": pipeline_id,
            "destination_id": destination_id,
            "reel_db_id": reel_db_id,
            "publication_id": publication_id,
            "priority": priority,
            "stage": stage,
            "scheduled_at": scheduled_at,
        },
    )
    res = await execute(
        """
        SELECT id, pipeline_id, destination_id, reel_db_id, publication_id,
               status, priority, stage, error_code, error,
               scheduled_at, queued_at, started_at, finished_at, created_at, updated_at
        FROM tiktok_publish_queue WHERE id = :id
        """,
        {"id": job_id},
    )
    return result_to_dict(res)


async def get_job(job_id: str) -> dict[str, Any] | None:
    res = await execute(
        """
        SELECT id, pipeline_id, destination_id, reel_db_id, publication_id,
               status, priority, stage, error_code, error,
               scheduled_at, queued_at, started_at, finished_at, created_at, updated_at
        FROM tiktok_publish_queue WHERE id = :id
        """,
        {"id": job_id},
    )
    return result_to_dict(res)


async def claim_next_job(worker_id: str) -> dict[str, Any] | None:
    """Atomically claim the highest-priority queued job whose scheduled time has arrived.

    - Auto jobs (priority < 1000): require pipeline auto_publish = 1 and scheduled_at <= NOW.
    - Manual jobs (priority >= 1000): processed immediately.
    """
    now = _now()
    res = await execute(
        """
        UPDATE tiktok_publish_queue
        SET status = 'processing', stage = 'claimed', started_at = :now,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = (
            SELECT q.id FROM tiktok_publish_queue q
            LEFT JOIN tiktok_pipelines p ON p.id = q.pipeline_id
            WHERE q.status = 'queued'
            AND (p.enabled IS NULL OR p.enabled = 1)
            AND (
                q.priority >= :manual_priority
                OR (
                    (p.auto_publish IS NULL OR p.auto_publish = 1)
                    AND (q.scheduled_at IS NULL OR q.scheduled_at <= :now)
                )
            )
            ORDER BY q.priority DESC, COALESCE(q.scheduled_at, q.queued_at) ASC, q.id ASC
            LIMIT 1
        )
        RETURNING id, pipeline_id, destination_id, reel_db_id, publication_id,
           status, priority, stage, error_code, error,
           scheduled_at, queued_at, started_at, finished_at, created_at, updated_at
        """,
        {"now": now, "manual_priority": MANUAL_JOB_PRIORITY},
    )
    if res.rows:
        row = result_to_dict(res)
        row["worker_id"] = worker_id
        return row
    return None


async def mark_job_stage(
    job_id: str,
    stage: str | None,
    error_code: str | None = None,
    error: str | None = None,
) -> None:
    updates = ["updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"]
    params: dict[str, Any] = {"id": job_id}
    if stage is not None:
        updates.append("stage = :stage")
        params["stage"] = stage
    if error_code is not None:
        updates.append("error_code = :err_code")
        params["err_code"] = error_code
    if error is not None:
        updates.append("error = :err")
        params["err"] = error
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
        SET status = 'queued', stage = NULL, started_at = NULL,
            error = :error, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = :id
        """,
        {"id": job_id, "error": error},
    )


async def cancel_job(job_id: str) -> bool:
    """Cancel an unprocessed queued or scheduled job."""
    res = await execute(
        """
        UPDATE tiktok_publish_queue
        SET status = 'cancelled', stage = 'cancelled',
            finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = :id AND status IN ('queued', 'scheduled')
        """,
        {"id": job_id},
    )
    success = (res.rows_affected > 0) if hasattr(res, "rows_affected") else False
    if success:
        # Also release the corresponding publication and reel
        job = await get_job(job_id)
        if job:
            from .publications import set_publication_status
            from .reels import update_reel_status

            await set_publication_status(job["publication_id"], "cancelled")
            await update_reel_status(job["reel_db_id"], "new")
    return success


async def retry_job(job_id: str) -> bool:
    """Reset a failed or cancelled job to queued state for retry."""
    job = await get_job(job_id)
    if not job or job.get("status") not in ("failed", "cancelled"):
        return False

    res = await execute(
        """
        UPDATE tiktok_publish_queue
        SET status = 'queued', stage = 'retrying', error = NULL, error_code = NULL,
            started_at = NULL, finished_at = NULL,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = :id
        """,
        {"id": job_id},
    )
    if hasattr(res, "rows_affected") and res.rows_affected > 0:
        from .publications import set_publication_status
        from .reels import update_reel_status

        await set_publication_status(job["publication_id"], "queued")
        await update_reel_status(job["reel_db_id"], "scheduled")
        return True
    return False


async def reschedule_job(job_id: str, new_scheduled_at: str) -> bool:
    """Update scheduled time for an unprocessed job."""
    res = await execute(
        """
        UPDATE tiktok_publish_queue
        SET scheduled_at = :scheduled_at,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = :id AND status IN ('queued', 'scheduled')
        """,
        {"id": job_id, "scheduled_at": new_scheduled_at},
    )
    if hasattr(res, "rows_affected") and res.rows_affected > 0:
        job = await get_job(job_id)
        if job and job.get("publication_id"):
            from .publications import set_scheduled_publish_at

            await set_scheduled_publish_at(job["publication_id"], new_scheduled_at)
        return True
    return False


async def list_queue_for_pipeline(pipeline_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Query queue items joined with publication, reel, source, and destination info."""
    res = await execute(
        """
        SELECT
            q.id,
            q.pipeline_id,
            q.destination_id,
            q.reel_db_id,
            q.publication_id,
            q.status,
            q.priority,
            q.stage,
            q.error_code,
            q.error,
            COALESCE(q.scheduled_at, pub.scheduled_publish_at) AS scheduled_at,
            q.queued_at,
            q.started_at,
            q.finished_at,
            q.created_at,
            r.caption AS reel_caption,
            r.reel_url,
            r.thumbnail_url,
            r.duration AS reel_duration,
            s.username AS source_username,
            d.channel_name AS destination_channel_name,
            d.channel_avatar_url AS destination_channel_avatar_url,
            COALESCE(pub.youtube_upload_mode, 'shorts') AS youtube_upload_mode,
            pub.youtube_video_id,
            pub.retry_count,
            pub.shorts_eligible,
            pub.shorts_check_note
        FROM tiktok_publish_queue q
        LEFT JOIN tiktok_publications pub ON pub.id = q.publication_id
        LEFT JOIN tiktok_reels r ON r.id = q.reel_db_id
        LEFT JOIN tiktok_sources s ON s.id = r.source_id
        LEFT JOIN youtube_destinations d ON d.id = q.destination_id
        WHERE q.pipeline_id = :pid
        ORDER BY
            CASE q.status
                WHEN 'processing' THEN 1
                WHEN 'queued' THEN 2
                WHEN 'scheduled' THEN 3
                WHEN 'failed' THEN 4
                ELSE 5
            END ASC,
            COALESCE(q.scheduled_at, q.queued_at) DESC,
            q.id DESC
        LIMIT :limit
        """,
        {"pid": pipeline_id, "limit": limit},
    )
    return result_to_dicts(res)


def _now() -> str:
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
