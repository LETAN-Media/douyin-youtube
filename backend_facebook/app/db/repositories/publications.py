from typing import Any
from datetime import datetime, timezone

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
        "SELECT id, reel_db_id, destination_id, status, youtube_video_id, youtube_title, youtube_description, youtube_hashtags_json, ai_model, started_at, published_at, scheduled_publish_at, last_error, retry_count, created_at, updated_at FROM publications WHERE id = :id",
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
        "youtube_title": r[5],
        "youtube_description": r[6],
        "youtube_hashtags_json": r[7],
        "ai_model": r[8],
        "started_at": r[9],
        "published_at": r[10],
        "scheduled_publish_at": r[11],
        "last_error": r[12],
        "retry_count": r[13],
        "created_at": r[14],
        "updated_at": r[15],
    }


async def get_by_reel_destination(
    reel_db_id: str, destination_id: str
) -> dict[str, Any] | None:
    client = get_client()
    rows = await client.execute(
        "SELECT id, reel_db_id, destination_id, status, youtube_video_id, youtube_title, youtube_description, youtube_hashtags_json, ai_model, started_at, published_at, scheduled_publish_at, last_error, retry_count, created_at, updated_at FROM publications WHERE reel_db_id = :reel_db_id AND destination_id = :destination_id",
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
        "youtube_title": r[5],
        "youtube_description": r[6],
        "youtube_hashtags_json": r[7],
        "ai_model": r[8],
        "started_at": r[9],
        "published_at": r[10],
        "scheduled_publish_at": r[11],
        "last_error": r[12],
        "retry_count": r[13],
        "created_at": r[14],
        "updated_at": r[15],
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


async def mark_scheduled(
    publication_id: str,
    youtube_video_id: str,
    scheduled_publish_at: str | None = None,
    *,
    title: str | None = None,
    description: str | None = None,
    hashtags: list[str] | None = None,
    ai_model: str | None = None,
) -> None:
    """Mark publication as scheduled with YouTube video ID and publishAt."""
    import json as _json

    client = get_client()
    await client.execute(
        "UPDATE publications SET status = 'scheduled', youtube_video_id = :youtube_video_id, "
        "scheduled_publish_at = :scheduled_publish_at, "
        "youtube_title = :title, youtube_description = :description, "
        "youtube_hashtags_json = :hashtags, ai_model = :ai_model, "
        "started_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {
            "youtube_video_id": youtube_video_id,
            "scheduled_publish_at": scheduled_publish_at,
            "title": title,
            "description": description,
            "hashtags": _json.dumps(hashtags or [], ensure_ascii=False),
            "ai_model": ai_model,
            "id": publication_id,
        },
    )


async def mark_published(
    publication_id: str,
    youtube_video_id: str,
    *,
    title: str | None = None,
    description: str | None = None,
    hashtags: list[str] | None = None,
    ai_model: str | None = None,
) -> None:
    """Mark published + snapshot the exact metadata uploaded. Never overwrites later."""
    import json as _json

    client = get_client()
    await client.execute(
        "UPDATE publications SET status = 'published', youtube_video_id = :youtube_video_id, "
        "youtube_title = :title, youtube_description = :description, "
        "youtube_hashtags_json = :hashtags, ai_model = :ai_model, "
        "published_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), last_error = NULL, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {
            "youtube_video_id": youtube_video_id,
            "title": title,
            "description": description,
            "hashtags": _json.dumps(hashtags or [], ensure_ascii=False),
            "ai_model": ai_model,
            "id": publication_id,
        },
    )


async def mark_failed(publication_id: str, error: str) -> None:
    client = get_client()
    await client.execute(
        "UPDATE publications SET status = 'failed', last_error = :error, "
        "retry_count = retry_count + 1, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {"error": (error or "")[:500], "id": publication_id},
    )


async def set_scheduled_publish_at(publication_id: str, scheduled_publish_at: str) -> None:
    """Set the scheduled_publish_at timestamp on an existing publication."""
    client = get_client()
    await client.execute(
        "UPDATE publications SET scheduled_publish_at = :scheduled_publish_at, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {"scheduled_publish_at": scheduled_publish_at, "id": publication_id},
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


async def list_publications(destination_id: str) -> list[dict[str, Any]]:
    client = get_client()
    rows = await client.execute(
        "SELECT id, reel_db_id, destination_id, status, youtube_video_id, youtube_title, youtube_description, youtube_hashtags_json, ai_model, started_at, published_at, scheduled_publish_at, last_error, retry_count, created_at, updated_at FROM publications WHERE destination_id = :destination_id",
        {"destination_id": destination_id},
    )
    return [
        {
            "id": r[0],
            "reel_db_id": r[1],
            "destination_id": r[2],
            "status": r[3],
            "youtube_video_id": r[4],
            "youtube_title": r[5],
            "youtube_description": r[6],
            "youtube_hashtags_json": r[7],
            "ai_model": r[8],
            "started_at": r[9],
            "published_at": r[10],
            "scheduled_publish_at": r[11],
            "last_error": r[12],
            "retry_count": r[13],
            "created_at": r[14],
            "updated_at": r[15],
        }
        for r in rows.rows
    ]


async def list_publications_for_pipeline(
    pipeline_id: str, *, limit: int = 100, offset: int = 0
) -> tuple[list[dict[str, Any]], int]:
    """Publications joined with reels + destinations. Safe fields only, no credentials."""
    client = get_client()
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    params: dict[str, Any] = {"pipeline_id": pipeline_id, "limit": limit, "offset": offset}
    rows = await client.execute(
        "SELECT p.id, p.reel_db_id, p.destination_id, p.status, p.youtube_video_id, "
        "p.started_at, p.published_at, p.last_error, p.retry_count, "
        "r.reel_id, d.channel_name "
        "FROM publications p "
        "JOIN facebook_reels r ON r.id = p.reel_db_id "
        "JOIN youtube_destinations d ON d.id = p.destination_id "
        "WHERE d.pipeline_id = :pipeline_id "
        "ORDER BY p.created_at DESC, p.id LIMIT :limit OFFSET :offset",
        params,
    )
    total_rows = await client.execute(
        "SELECT COUNT(*) FROM publications p "
        "JOIN youtube_destinations d ON d.id = p.destination_id "
        "WHERE d.pipeline_id = :pipeline_id",
        {"pipeline_id": pipeline_id},
    )
    total = total_rows.rows[0][0] if total_rows.rows else 0
    return (
        [
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
                "reel_id": r[9],
                "channel_name": r[10],
            }
            for r in rows.rows
        ],
        total,
    )


async def list_due_scheduled_publications(limit: int = 20) -> list[dict[str, Any]]:
    """Scheduled publications whose scheduled_publish_at has arrived or passed."""
    client = get_client()
    cutoff = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = await client.execute(
        "SELECT p.id, p.reel_db_id, p.destination_id, p.status, p.youtube_video_id, "
        "p.started_at, p.published_at, p.last_error, p.retry_count, "
        "p.scheduled_publish_at, r.reel_id, d.channel_name, d.pipeline_id "
        "FROM publications p "
        "JOIN facebook_reels r ON r.id = p.reel_db_id "
        "JOIN youtube_destinations d ON d.id = p.destination_id "
        "WHERE p.status = 'scheduled' AND p.scheduled_publish_at <= :cutoff "
        "ORDER BY p.scheduled_publish_at ASC, p.id ASC LIMIT :limit",
        {"cutoff": cutoff, "limit": max(1, min(limit, 100))},
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
            "scheduled_publish_at": r[9],
            "reel_id": r[10],
            "channel_name": r[11],
            "pipeline_id": r[12],
        }
        for r in rows.rows
    ]
