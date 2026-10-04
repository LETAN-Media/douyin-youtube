from typing import Any

from ..client import get_client

_COLUMNS = (
    "id, source_id, started_at, completed_at, discovered_count, inserted_count, "
    "existing_count, crawl_complete, status, error, stop_reason, scan_mode"
)


def _row_to_dict(r: Any) -> dict[str, Any]:
    return {
        "id": r[0],
        "source_id": r[1],
        "started_at": r[2],
        "completed_at": r[3],
        "discovered_count": r[4],
        "inserted_count": r[5],
        "existing_count": r[6],
        "crawl_complete": bool(r[7]),
        "status": r[8],
        "error": r[9],
        "stop_reason": r[10] if len(r) > 10 else None,
        "scan_mode": r[11] if len(r) > 11 else None,
    }


async def create_scan_run(
    *,
    scan_run_id: str,
    source_id: str,
    status: str = "running",
    scan_mode: str = "initial",
) -> dict[str, Any]:
    client = get_client()
    await client.execute(
        """
        INSERT INTO scan_runs (id, source_id, status, scan_mode)
        VALUES (:id, :source_id, :status, :scan_mode)
        """,
        {
            "id": scan_run_id,
            "source_id": source_id,
            "status": status,
            "scan_mode": scan_mode,
        },
    )
    return {
        "id": scan_run_id,
        "source_id": source_id,
        "status": status,
        "discovered_count": 0,
        "inserted_count": 0,
        "existing_count": 0,
        "crawl_complete": False,
        "error": None,
        "stop_reason": None,
        "scan_mode": scan_mode,
    }


async def get_scan_run(scan_run_id: str) -> dict[str, Any] | None:
    client = get_client()
    rows = await client.execute(
        f"SELECT {_COLUMNS} FROM scan_runs WHERE id = :id",
        {"id": scan_run_id},
    )
    if not rows.rows:
        return None
    return _row_to_dict(rows.rows[0])


async def list_scan_runs(source_id: str) -> list[dict[str, Any]]:
    client = get_client()
    rows = await client.execute(
        f"SELECT {_COLUMNS} FROM scan_runs WHERE source_id = :source_id ORDER BY started_at DESC",
        {"source_id": source_id},
    )
    return [_row_to_dict(r) for r in rows.rows]


async def latest_scan_run(source_id: str) -> dict[str, Any] | None:
    """Most recent scan run for a source (any status), or None if never scanned."""
    client = get_client()
    rows = await client.execute(
        f"SELECT {_COLUMNS} FROM scan_runs WHERE source_id = :source_id "
        "ORDER BY started_at DESC LIMIT 1",
        {"source_id": source_id},
    )
    if not rows.rows:
        return None
    return _row_to_dict(rows.rows[0])


async def get_active_scan_run(source_id: str) -> dict[str, Any] | None:
    """The single queued/running scan for a source, if any."""
    client = get_client()
    rows = await client.execute(
        f"SELECT {_COLUMNS} FROM scan_runs WHERE source_id = :source_id "
        "AND status IN ('queued', 'running') ORDER BY started_at DESC LIMIT 1",
        {"source_id": source_id},
    )
    if not rows.rows:
        return None
    return _row_to_dict(rows.rows[0])


async def mark_running(scan_run_id: str) -> None:
    client = get_client()
    await client.execute(
        "UPDATE scan_runs SET status = 'running' WHERE id = :id AND status = 'queued'",
        {"id": scan_run_id},
    )


async def set_scan_mode(scan_run_id: str, scan_mode: str) -> None:
    client = get_client()
    await client.execute(
        "UPDATE scan_runs SET scan_mode = :scan_mode WHERE id = :id",
        {"scan_mode": scan_mode, "id": scan_run_id},
    )


async def update_progress(
    scan_run_id: str,
    *,
    discovered_count: int,
    inserted_count: int,
    existing_count: int,
) -> None:
    client = get_client()
    await client.execute(
        "UPDATE scan_runs SET discovered_count = :discovered_count, "
        "inserted_count = :inserted_count, existing_count = :existing_count "
        "WHERE id = :id",
        {
            "id": scan_run_id,
            "discovered_count": discovered_count,
            "inserted_count": inserted_count,
            "existing_count": existing_count,
        },
    )


async def complete_scan_run(
    scan_run_id: str,
    *,
    discovered_count: int = 0,
    inserted_count: int = 0,
    existing_count: int = 0,
    status: str = "completed",
    crawl_complete: bool = False,
    stop_reason: str | None = None,
    error: str | None = None,
) -> None:
    client = get_client()
    await client.execute(
        "UPDATE scan_runs SET status = :status, "
        "completed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), "
        "discovered_count = :discovered_count, inserted_count = :inserted_count, "
        "existing_count = :existing_count, crawl_complete = :crawl_complete, "
        "stop_reason = :stop_reason, error = :error WHERE id = :id",
        {
            "status": status,
            "id": scan_run_id,
            "discovered_count": discovered_count,
            "inserted_count": inserted_count,
            "existing_count": existing_count,
            "crawl_complete": 1 if crawl_complete else 0,
            "stop_reason": stop_reason,
            "error": error,
        },
    )


async def fail_stale_scan_runs(reason: str = "interrupted: process restarted") -> int:
    """Mark orphaned queued/running scans as failed (startup recovery)."""
    client = get_client()
    rows = await client.execute(
        "SELECT id FROM scan_runs WHERE status IN ('queued', 'running')"
    )
    ids = [r[0] for r in (rows.rows or [])]
    for scan_id in ids:
        await complete_scan_run(
            scan_id, status="failed", error=reason, stop_reason="INTERRUPTED"
        )
    return len(ids)
