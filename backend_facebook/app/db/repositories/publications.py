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
