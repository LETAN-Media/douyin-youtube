from typing import Any

from ..client import get_client


async def create_source(
    *,
    source_id: str,
    pipeline_id: str,
    page_id: str,
    page_name: str,
    reels_url: str | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    client = get_client()
    await client.execute(
        """
        INSERT INTO facebook_sources (id, pipeline_id, page_id, page_name, reels_url, enabled)
        VALUES (:id, :pipeline_id, :page_id, :page_name, :reels_url, :enabled)
        """,
        {
            "id": source_id,
            "pipeline_id": pipeline_id,
            "page_id": page_id,
            "page_name": page_name,
            "reels_url": reels_url,
            "enabled": 1 if enabled else 0,
        },
    )
    return {
        "id": source_id,
        "pipeline_id": pipeline_id,
        "page_id": page_id,
        "page_name": page_name,
        "reels_url": reels_url,
        "enabled": enabled,
    }


async def get_source(source_id: str) -> dict[str, Any] | None:
    client = get_client()
    rows = await client.execute(
        "SELECT id, pipeline_id, page_id, page_name, reels_url, enabled, initial_scan_completed, crawl_complete, discovered_total, last_scan_at, last_scan_status, last_scan_error, created_at, updated_at FROM facebook_sources WHERE id = :id",
        {"id": source_id},
    )
    if not rows.rows:
        return None
    r = rows.rows[0]
    return {
        "id": r[0],
        "pipeline_id": r[1],
        "page_id": r[2],
        "page_name": r[3],
        "reels_url": r[4],
        "enabled": bool(r[5]),
        "initial_scan_completed": bool(r[6]),
        "crawl_complete": bool(r[7]),
        "discovered_total": r[8],
        "last_scan_at": r[9],
        "last_scan_status": r[10],
        "last_scan_error": r[11],
        "created_at": r[12],
        "updated_at": r[13],
    }


async def list_sources(pipeline_id: str) -> list[dict[str, Any]]:
    client = get_client()
    rows = await client.execute(
        "SELECT id, pipeline_id, page_id, page_name, reels_url, enabled, initial_scan_completed, crawl_complete, discovered_total, last_scan_at, last_scan_status, last_scan_error, created_at, updated_at FROM facebook_sources WHERE pipeline_id = :pipeline_id",
        {"pipeline_id": pipeline_id},
    )
    return [
        {
            "id": r[0],
            "pipeline_id": r[1],
            "page_id": r[2],
            "page_name": r[3],
            "reels_url": r[4],
            "enabled": bool(r[5]),
            "initial_scan_completed": bool(r[6]),
            "crawl_complete": bool(r[7]),
            "discovered_total": r[8],
            "last_scan_at": r[9],
            "last_scan_status": r[10],
            "last_scan_error": r[11],
            "created_at": r[12],
            "updated_at": r[13],
        }
        for r in rows.rows
    ]
