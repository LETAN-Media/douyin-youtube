from typing import Any

from ..client import get_client


async def create_scan_run(
    *,
    scan_run_id: str,
    source_id: str,
    status: str = "running",
) -> dict[str, Any]:
    client = get_client()
    await client.execute(
        """
        INSERT INTO scan_runs (id, source_id, status)
        VALUES (:id, :source_id, :status)
        """,
        {
            "id": scan_run_id,
            "source_id": source_id,
            "status": status,
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
    }


async def get_scan_run(scan_run_id: str) -> dict[str, Any] | None:
    client = get_client()
    rows = await client.execute(
        "SELECT id, source_id, started_at, completed_at, discovered_count, inserted_count, existing_count, crawl_complete, status, error FROM scan_runs WHERE id = :id",
        {"id": scan_run_id},
    )
    if not rows.rows:
        return None
    r = rows.rows[0]
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
    }


async def list_scan_runs(source_id: str) -> list[dict[str, Any]]:
    client = get_client()
    rows = await client.execute(
        "SELECT id, source_id, started_at, completed_at, discovered_count, inserted_count, existing_count, crawl_complete, status, error FROM scan_runs WHERE source_id = :source_id ORDER BY started_at DESC",
        {"source_id": source_id},
    )
    return [
        {
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
        }
        for r in rows.rows
    ]


async def complete_scan_run(
    scan_run_id: str,
    *,
    discovered_count: int = 0,
    inserted_count: int = 0,
    existing_count: int = 0,
    status: str = "completed",
) -> None:
    client = get_client()
    await client.execute(
        "UPDATE scan_runs SET status = :status, completed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), discovered_count = :discovered_count, inserted_count = :inserted_count, existing_count = :existing_count WHERE id = :id",
        {
            "status": status,
            "id": scan_run_id,
            "discovered_count": discovered_count,
            "inserted_count": inserted_count,
            "existing_count": existing_count,
        },
    )
