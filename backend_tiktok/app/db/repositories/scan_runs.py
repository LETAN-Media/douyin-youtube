from typing import Any

from ...db.client import execute, result_to_dict, result_to_dicts


async def create_scan_run(
    scan_run_id: str,
    source_id: str,
    scan_mode: str = "initial",
) -> dict[str, Any]:
    await execute(
        """
        INSERT INTO tiktok_scan_runs (id, source_id, scan_mode)
        VALUES (:id, :source_id, :scan_mode)
        """,
        {"id": scan_run_id, "source_id": source_id, "scan_mode": scan_mode},
    )
    row = await get_scan_run(scan_run_id)
    assert row is not None
    return row


async def get_scan_run(scan_run_id: str) -> dict[str, Any] | None:
    res = await execute(
        "SELECT id, source_id, started_at, completed_at, discovered_count, "
        "inserted_count, existing_count, crawl_complete, status, error, scan_mode "
        "FROM tiktok_scan_runs WHERE id = :id",
        {"id": scan_run_id},
    )
    return result_to_dict(res)


async def complete_scan_run(
    scan_run_id: str,
    discovered_count: int = 0,
    inserted_count: int = 0,
    existing_count: int = 0,
    crawl_complete: bool = True,
    status: str = "completed",
    error: str | None = None,
    stop_reason: str | None = None,
) -> None:
    await execute(
        """
        UPDATE tiktok_scan_runs
        SET completed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
            discovered_count = :discovered_count,
            inserted_count = :inserted_count,
            existing_count = :existing_count,
            crawl_complete = :crawl_complete,
            status = :status,
            error = :error,
            stop_reason = :stop_reason
        WHERE id = :id
        """,
        {
            "id": scan_run_id,
            "discovered_count": discovered_count,
            "inserted_count": inserted_count,
            "existing_count": existing_count,
            "crawl_complete": 1 if crawl_complete else 0,
            "status": status,
            "error": error,
            "stop_reason": stop_reason,
        },
    )


async def set_scan_run_status(scan_run_id: str, status: str) -> None:
    await execute(
        "UPDATE tiktok_scan_runs SET status = :status WHERE id = :id",
        {"id": scan_run_id, "status": status},
    )


async def mark_scan_run_error(scan_run_id: str, error: str) -> None:
    await execute(
        "UPDATE tiktok_scan_runs SET status = 'error', error = :error, "
        "completed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {"id": scan_run_id, "error": error},
    )
