from typing import Any

from ..client import get_client


class DuplicateSourceError(Exception):
    """Raised when (pipeline_id, page_id) already exists."""


def _is_unique_violation(exc: Exception) -> bool:
    msg = str(exc).upper()
    return "UNIQUE" in msg and (
        "FACEBOOK_SOURCES" in msg or "PIPELINE_PAGE" in msg or "PIPELINE_ID" in msg or "PAGE_ID" in msg
    )


async def get_source_by_page(pipeline_id: str, page_id: str) -> dict[str, Any] | None:
    client = get_client()
    rows = await client.execute(
        "SELECT id, pipeline_id, page_id, page_name, reels_url, enabled, initial_scan_completed, crawl_complete, discovered_total, last_scan_at, last_scan_status, last_scan_error, created_at, updated_at FROM facebook_sources WHERE pipeline_id = :pipeline_id AND page_id = :page_id LIMIT 1",
        {"pipeline_id": pipeline_id, "page_id": page_id},
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


async def create_source(
    *,
    source_id: str,
    pipeline_id: str,
    page_id: str,
    page_name: str | None = None,
    reels_url: str | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    # Guard at repository layer: same page_id in the same pipeline is forbidden.
    existing = await get_source_by_page(pipeline_id, page_id)
    if existing is not None:
        raise DuplicateSourceError(
            f"Facebook source already exists in this pipeline (page_id={page_id})"
        )
    client = get_client()
    try:
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
    except Exception as exc:
        if _is_unique_violation(exc):
            raise DuplicateSourceError(
                f"Facebook source already exists in this pipeline (page_id={page_id})"
            ) from exc
        raise
    created = await get_source(source_id)
    if created is not None:
        return created
    return {
        "id": source_id,
        "pipeline_id": pipeline_id,
        "page_id": page_id,
        "page_name": page_name,
        "reels_url": reels_url,
        "enabled": enabled,
        "initial_scan_completed": False,
        "crawl_complete": False,
        "discovered_total": 0,
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


async def record_scan_finished(
    source_id: str,
    *,
    status: str,
    error: str | None,
    discovered_total: int,
    crawl_complete: bool,
) -> None:
    """Persist scan outcome on the source. Completion flags only set on full crawl."""
    client = get_client()
    if crawl_complete:
        await client.execute(
            "UPDATE facebook_sources SET last_scan_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), "
            "last_scan_status = :status, last_scan_error = :error, "
            "discovered_total = :total, initial_scan_completed = 1, crawl_complete = 1, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
            {"status": status, "error": error, "total": discovered_total, "id": source_id},
        )
    else:
        await client.execute(
            "UPDATE facebook_sources SET last_scan_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), "
            "last_scan_status = :status, last_scan_error = :error, "
            "discovered_total = :total, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
            {"status": status, "error": error, "total": discovered_total, "id": source_id},
        )
