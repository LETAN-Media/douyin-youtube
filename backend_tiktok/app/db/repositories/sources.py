from typing import Any

from ...db.client import execute, result_to_dict, result_to_dicts


async def create_source(
    source_id: str,
    pipeline_id: str,
    username: str,
    display_name: str | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    await execute(
        """
        INSERT INTO tiktok_sources (id, pipeline_id, username, display_name, source_url)
        VALUES (:id, :pipeline_id, :username, :display_name, :source_url)
        """,
        {
            "id": source_id,
            "pipeline_id": pipeline_id,
            "username": username,
            "display_name": display_name,
            "source_url": source_url,
        },
    )
    row = await get_source(source_id)
    assert row is not None
    return row


async def get_source(source_id: str) -> dict[str, Any] | None:
    res = await execute(
        "SELECT id, pipeline_id, username, display_name, source_url, enabled, "
        "initial_scan_completed, crawl_complete, discovered_total, "
        "last_scan_at, last_scan_status, last_scan_error, created_at, updated_at "
        "FROM tiktok_sources WHERE id = :id",
        {"id": source_id},
    )
    return result_to_dict(res)


async def list_sources(pipeline_id: str) -> list[dict[str, Any]]:
    res = await execute(
        "SELECT id, pipeline_id, username, display_name, source_url, enabled, "
        "initial_scan_completed, crawl_complete, discovered_total, "
        "last_scan_at, last_scan_status, last_scan_error, created_at, updated_at "
        "FROM tiktok_sources WHERE pipeline_id = :pipeline_id ORDER BY created_at",
        {"pipeline_id": pipeline_id},
    )
    return result_to_dicts(res)


async def update_scan_state(
    source_id: str,
    scan_status: str | None = None,
    scan_error: str | None = None,
    discovered_total: int | None = None,
    initial_scan_completed: bool | None = None,
    crawl_complete: bool | None = None,
) -> None:
    updates: list[str] = ["updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"]
    params: dict[str, Any] = {"id": source_id}
    if scan_status is not None:
        updates.append("last_scan_status = :scan_status")
        params["scan_status"] = scan_status
    if scan_error is not None:
        updates.append("last_scan_error = :scan_error")
        params["scan_error"] = scan_error
    if discovered_total is not None:
        updates.append("discovered_total = :discovered_total")
        params["discovered_total"] = discovered_total
    if initial_scan_completed is not None:
        updates.append("initial_scan_completed = :isc")
        params["isc"] = 1 if initial_scan_completed else 0
    if crawl_complete is not None:
        updates.append("crawl_complete = :cc")
        params["cc"] = 1 if crawl_complete else 0
    updates.append("last_scan_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')")
    await execute(
        f"UPDATE tiktok_sources SET {', '.join(updates)} WHERE id = :id",
        params,
    )
