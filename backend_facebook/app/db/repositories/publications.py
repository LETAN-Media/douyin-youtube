from typing import Any

from ..client import get_client


async def create_publication(
    *,
    publication_id: str,
    reel_db_id: str,
    destination_id: str,
    status: str = "queued",
) -> dict[str, Any]:
    client = get_client()
    await client.execute(
        """
        INSERT INTO publications (id, reel_db_id, destination_id, status)
        VALUES (:id, :reel_db_id, :destination_id, :status)
        """,
        {
            "id": publication_id,
            "reel_db_id": reel_db_id,
            "destination_id": destination_id,
            "status": status,
        },
    )
    return {
        "id": publication_id,
        "reel_db_id": reel_db_id,
        "destination_id": destination_id,
        "status": status,
    }


async def get_publication(publication_id: str) -> dict[str, Any] | None:
    client = get_client()
    rows = await client.execute(
        "SELECT id, reel_db_id, destination_id, status, youtube_video_id, started_at, published_at, last_error, retry_count, created_at, updated_at FROM publications WHERE id = :id",
        {"id": publication_id},
    )
    if not rows.rows:
        return None
    r = rows.rows[0]
    return {
        "id": r[0],
        "reel_db_id": r[1],
        "destination_id": r[2],
        "status": r[3],
        "youtube_video_id": r[4],
        "started_at": r[5],
        "published_at": r[6],
        "last_error": r[7],
        "retry_count": r[8],
        "created_at": r[9],
        "updated_at": r[10],
    }


async def get_by_reel_destination(
    reel_db_id: str, destination_id: str
) -> dict[str, Any] | None:
    client = get_client()
    rows = await client.execute(
        "SELECT id, reel_db_id, destination_id, status, youtube_video_id, started_at, published_at, last_error, retry_count, created_at, updated_at FROM publications WHERE reel_db_id = :reel_db_id AND destination_id = :destination_id",
        {"reel_db_id": reel_db_id, "destination_id": destination_id},
    )
    if not rows.rows:
        return None
    r = rows.rows[0]
    return {
        "id": r[0],
        "reel_db_id": r[1],
        "destination_id": r[2],
        "status": r[3],
        "youtube_video_id": r[4],
        "started_at": r[5],
        "published_at": r[6],
        "last_error": r[7],
        "retry_count": r[8],
        "created_at": r[9],
        "updated_at": r[10],
    }


async def get_or_create(
    *, publication_id: str, reel_db_id: str, destination_id: str
) -> tuple[dict[str, Any], bool]:
    """Idempotent create. Returns (row, created). UNIQUE race resolves to existing."""
    existing = await get_by_reel_destination(reel_db_id, destination_id)
    if existing is not None:
        return existing, False
    client = get_client()
    try:
        await client.execute(
            """
            INSERT INTO publications (id, reel_db_id, destination_id, status)
            VALUES (:id, :reel_db_id, :destination_id, 'queued')
            """,
            {"id": publication_id, "reel_db_id": reel_db_id, "destination_id": destination_id},
        )
    except Exception:
        existing = await get_by_reel_destination(reel_db_id, destination_id)
        if existing is not None:
            return existing, False
        raise
    row = await get_publication(publication_id)
    assert row is not None
    return row, True


async def mark_processing(publication_id: str) -> None:
    client = get_client()
    await client.execute(
        "UPDATE publications SET status = 'processing', "
        "started_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {"id": publication_id},
    )


async def mark_published(publication_id: str, youtube_video_id: str) -> None:
    client = get_client()
    await client.execute(
        "UPDATE publications SET status = 'published', youtube_video_id = :youtube_video_id, "
        "published_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), last_error = NULL, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {"youtube_video_id": youtube_video_id, "id": publication_id},
    )


async def mark_failed(publication_id: str, error: str) -> None:
    client = get_client()
    await client.execute(
        "UPDATE publications SET status = 'failed', last_error = :error, "
        "retry_count = retry_count + 1, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {"error": (error or "")[:500], "id": publication_id},
    )


async def status_counts_for_pipeline(pipeline_id: str) -> dict[str, int]:
    """Publication status histogram across a pipeline's destinations. No N+1."""
    client = get_client()
    rows = await client.execute(
        "SELECT p.status, COUNT(*) FROM publications p WHERE p.destination_id IN "
        "(SELECT id FROM youtube_destinations WHERE pipeline_id = :pipeline_id) "
        "GROUP BY p.status",
        {"pipeline_id": pipeline_id},
    )
    return {r[0]: r[1] for r in (rows.rows or [])}
    client = get_client()
    rows = await client.execute(
        "SELECT id, reel_db_id, destination_id, status, youtube_video_id, started_at, published_at, last_error, retry_count, created_at, updated_at FROM publications WHERE id = :id",
        {"id": publication_id},
    )
    if not rows.rows:
        return None
    r = rows.rows[0]
    return {
        "id": r[0],
        "reel_db_id": r[1],
        "destination_id": r[2],
        "status": r[3],
        "youtube_video_id": r[4],
        "started_at": r[5],
        "published_at": r[6],
        "last_error": r[7],
        "retry_count": r[8],
        "created_at": r[9],
        "updated_at": r[10],
    }


async def list_publications(destination_id: str) -> list[dict[str, Any]]:
    client = get_client()
    rows = await client.execute(
        "SELECT id, reel_db_id, destination_id, status, youtube_video_id, started_at, published_at, last_error, retry_count, created_at, updated_at FROM publications WHERE destination_id = :destination_id",
        {"destination_id": destination_id},
    )
    return [
        {
            "id": r[0],
            "reel_db_id": r[1],
            "destination_id": r[2],
            "status": r[3],
            "youtube_video_id": r[4],
            "started_at": r[5],
            "published_at": r[6],
            "last_error": r[7],
            "retry_count": r[8],
            "created_at": r[9],
            "updated_at": r[10],
        }
        for r in rows.rows
    ]
