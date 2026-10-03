from typing import Any

from ..client import get_client


async def insert_reel_if_new(
    *,
    reel_db_id: str,
    source_id: str,
    reel_id: str,
    reel_url: str | None = None,
    caption: str | None = None,
    thumbnail_url: str | None = None,
    source_published_at: str | None = None,
) -> tuple[str, dict[str, Any]]:
    client = get_client()
    existing = await client.execute(
        "SELECT id, source_id, reel_id, reel_url, caption, thumbnail_url, source_published_at, discovered_at, status, retry_count, last_error, youtube_video_id, youtube_published_at, created_at, updated_at FROM facebook_reels WHERE source_id = :source_id AND reel_id = :reel_id",
        {"source_id": source_id, "reel_id": reel_id},
    )
    if existing.rows:
        r = existing.rows[0]
        return "ALREADY_EXISTS", {
            "id": r[0],
            "source_id": r[1],
            "reel_id": r[2],
            "reel_url": r[3],
            "caption": r[4],
            "thumbnail_url": r[5],
            "source_published_at": r[6],
            "discovered_at": r[7],
            "status": r[8],
            "retry_count": r[9],
            "last_error": r[10],
            "youtube_video_id": r[11],
            "youtube_published_at": r[12],
            "created_at": r[13],
            "updated_at": r[14],
        }
    await client.execute(
        """
        INSERT INTO facebook_reels (id, source_id, reel_id, reel_url, caption, thumbnail_url, source_published_at)
        VALUES (:id, :source_id, :reel_id, :reel_url, :caption, :thumbnail_url, :source_published_at)
        """,
        {
            "id": reel_db_id,
            "source_id": source_id,
            "reel_id": reel_id,
            "reel_url": reel_url,
            "caption": caption,
            "thumbnail_url": thumbnail_url,
            "source_published_at": source_published_at,
        },
    )
    rows = await client.execute(
        "SELECT id, source_id, reel_id, reel_url, caption, thumbnail_url, source_published_at, discovered_at, status, retry_count, last_error, youtube_video_id, youtube_published_at, created_at, updated_at FROM facebook_reels WHERE id = :id",
        {"id": reel_db_id},
    )
    row = rows.rows[0]
    return "INSERTED", {
        "id": row[0],
        "source_id": row[1],
        "reel_id": row[2],
        "reel_url": row[3],
        "caption": row[4],
        "thumbnail_url": row[5],
        "source_published_at": row[6],
        "discovered_at": row[7],
        "status": row[8],
        "retry_count": row[9],
        "last_error": row[10],
        "youtube_video_id": row[11],
        "youtube_published_at": row[12],
        "created_at": row[13],
        "updated_at": row[14],
    }


async def get_reel(reel_db_id: str) -> dict[str, Any] | None:
    client = get_client()
    rows = await client.execute(
        "SELECT id, source_id, reel_id, reel_url, caption, thumbnail_url, source_published_at, discovered_at, status, retry_count, last_error, youtube_video_id, youtube_published_at, created_at, updated_at FROM facebook_reels WHERE id = :id",
        {"id": reel_db_id},
    )
    if not rows.rows:
        return None
    r = rows.rows[0]
    return {
        "id": r[0],
        "source_id": r[1],
        "reel_id": r[2],
        "reel_url": r[3],
        "caption": r[4],
        "thumbnail_url": r[5],
        "source_published_at": r[6],
        "discovered_at": r[7],
        "status": r[8],
        "retry_count": r[9],
        "last_error": r[10],
        "youtube_video_id": r[11],
        "youtube_published_at": r[12],
        "created_at": r[13],
        "updated_at": r[14],
    }


async def list_reels(source_id: str) -> list[dict[str, Any]]:
    client = get_client()
    rows = await client.execute(
        "SELECT id, source_id, reel_id, reel_url, caption, thumbnail_url, source_published_at, discovered_at, status, retry_count, last_error, youtube_video_id, youtube_published_at, created_at, updated_at FROM facebook_reels WHERE source_id = :source_id ORDER BY discovered_at",
        {"source_id": source_id},
    )
    return [
        {
            "id": r[0],
            "source_id": r[1],
            "reel_id": r[2],
            "reel_url": r[3],
            "caption": r[4],
            "thumbnail_url": r[5],
            "source_published_at": r[6],
            "discovered_at": r[7],
            "status": r[8],
            "retry_count": r[9],
            "last_error": r[10],
            "youtube_video_id": r[11],
            "youtube_published_at": r[12],
            "created_at": r[13],
            "updated_at": r[14],
        }
        for r in rows.rows
    ]


async def list_unpublished_reels(source_id: str) -> list[dict[str, Any]]:
    client = get_client()
    rows = await client.execute(
        "SELECT id, source_id, reel_id, reel_url, caption, thumbnail_url, source_published_at, discovered_at, status, retry_count, last_error, youtube_video_id, youtube_published_at, created_at, updated_at FROM facebook_reels WHERE source_id = :source_id AND status NOT IN ('published', 'skipped') ORDER BY discovered_at",
        {"source_id": source_id},
    )
    return [
        {
            "id": r[0],
            "source_id": r[1],
            "reel_id": r[2],
            "reel_url": r[3],
            "caption": r[4],
            "thumbnail_url": r[5],
            "source_published_at": r[6],
            "discovered_at": r[7],
            "status": r[8],
            "retry_count": r[9],
            "last_error": r[10],
            "youtube_video_id": r[11],
            "youtube_published_at": r[12],
            "created_at": r[13],
            "updated_at": r[14],
        }
        for r in rows.rows
    ]


async def count_reels(source_id: str | None = None) -> int:
    client = get_client()
    if source_id:
        rows = await client.execute(
            "SELECT COUNT(*) FROM facebook_reels WHERE source_id = :source_id",
            {"source_id": source_id},
        )
    else:
        rows = await client.execute("SELECT COUNT(*) FROM facebook_reels")
    return rows.rows[0][0] if rows.rows else 0


async def count_unpublished(source_id: str) -> int:
    client = get_client()
    rows = await client.execute(
        "SELECT COUNT(*) FROM facebook_reels WHERE source_id = :source_id AND status NOT IN ('published', 'skipped')",
        {"source_id": source_id},
    )
    return rows.rows[0][0] if rows.rows else 0


async def count_published(source_id: str) -> int:
    client = get_client()
    rows = await client.execute(
        "SELECT COUNT(*) FROM facebook_reels WHERE source_id = :source_id AND status = 'published'",
        {"source_id": source_id},
    )
    return rows.rows[0][0] if rows.rows else 0


async def update_reel_status(reel_db_id: str, status: str) -> None:
    client = get_client()
    await client.execute(
        "UPDATE facebook_reels SET status = :status, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {"status": status, "id": reel_db_id},
    )
