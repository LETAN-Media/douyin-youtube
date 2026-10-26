import time
from typing import Any

from ...db.client import execute, result_to_dict, result_to_dicts


def _gen_reel_db_id() -> str:
    return f"tiktok_{int(time.time() * 1000)}_{id(object()) & 0xFFFFFF}"


async def insert_reel_if_new(
    reel_db_id: str | None = None,
    source_id: str = "",
    reel_id: str = "",
    reel_url: str | None = None,
    caption: str | None = None,
    thumbnail_url: str | None = None,
    source_published_at: str | None = None,
    duration: int | None = None,
    play_count: int | None = None,
) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
    """Insert or detect existing reel.

    Returns (status, existing_row, new_row).
      status is INSERTED, ALREADY_EXISTS, or UPDATED_CAPTION.
    """
    db_id = reel_db_id or _gen_reel_db_id()
    existing = await _get_by_source_and_reel_id(source_id, reel_id)
    if existing:
        updated = False
        if caption and existing.get("caption") != caption:
            await execute(
                "UPDATE tiktok_reels SET caption = :caption, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
                "WHERE id = :id",
                {"id": existing["id"], "caption": caption},
            )
            updated = True
        row = await get_reel(existing["id"])
        return ("UPDATED_CAPTION" if updated else "ALREADY_EXISTS", row, None)
    await execute(
        """
        INSERT INTO tiktok_reels
            (id, source_id, reel_id, reel_url, caption, thumbnail_url,
             source_published_at, duration, play_count)
        VALUES
            (:id, :source_id, :reel_id, :reel_url, :caption, :thumbnail_url,
             :source_published_at, :duration, :play_count)
        """,
        {
            "id": db_id,
            "source_id": source_id,
            "reel_id": reel_id,
            "reel_url": reel_url,
            "caption": caption,
            "thumbnail_url": thumbnail_url,
            "source_published_at": source_published_at,
            "duration": duration,
            "play_count": play_count,
        },
    )
    row = await get_reel(db_id)
    assert row is not None
    return ("INSERTED", row, row)


async def _get_by_source_and_reel_id(source_id: str, reel_id: str) -> dict[str, Any] | None:
    res = await execute(
        "SELECT id FROM tiktok_reels WHERE source_id = :source_id AND reel_id = :reel_id",
        {"source_id": source_id, "reel_id": reel_id},
    )
    if res.rows:
        return await get_reel(res.rows[0][0])
    return None


async def get_reel(reel_db_id: str) -> dict[str, Any] | None:
    res = await execute(
        "SELECT id, source_id, reel_id, reel_url, caption, thumbnail_url, "
        "source_published_at, duration, play_count, discovered_at, status, "
        "retry_count, last_error, youtube_video_id, youtube_published_at, "
        "created_at, updated_at FROM tiktok_reels WHERE id = :id",
        {"id": reel_db_id},
    )
    return result_to_dict(res)


async def list_reels(source_id: str) -> list[dict[str, Any]]:
    res = await execute(
        "SELECT id, source_id, reel_id, reel_url, caption, thumbnail_url, "
        "source_published_at, duration, play_count, discovered_at, status, "
        "retry_count, last_error, youtube_video_id, youtube_published_at, "
        "created_at, updated_at FROM tiktok_reels WHERE source_id = :source_id "
        "ORDER BY discovered_at DESC",
        {"source_id": source_id},
    )
    return result_to_dicts(res)


async def list_unpublished_reels(source_id: str, limit: int = 50) -> list[dict[str, Any]]:
    res = await execute(
        "SELECT id, source_id, reel_id, reel_url, caption, thumbnail_url, "
        "source_published_at, duration, play_count, discovered_at, status, "
        "retry_count, last_error, youtube_video_id, youtube_published_at, "
        "created_at, updated_at FROM tiktok_reels "
        "WHERE source_id = :source_id AND status IN ('new', 'failed', 'error') "
        "ORDER BY discovered_at DESC LIMIT :limit",
        {"source_id": source_id, "limit": limit},
    )
    return result_to_dicts(res)


async def advance_status(reel_db_id: str, old_status: str, new_status: str) -> bool:
    res = await execute(
        "UPDATE tiktok_reels SET status = :new_status, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = :id AND status = :old_status",
        {"id": reel_db_id, "old_status": old_status, "new_status": new_status},
    )
    return res.rows_affected > 0 if hasattr(res, "rows_affected") else False


async def update_reel_status(reel_db_id: str, status: str) -> None:
    await execute(
        "UPDATE tiktok_reels SET status = :status, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = :id",
        {"id": reel_db_id, "status": status},
    )


async def mark_reel_scheduled(reel_db_id: str, youtube_video_id: str) -> None:
    await execute(
        "UPDATE tiktok_reels SET status = 'scheduled', youtube_video_id = :yt_id, "
        "youtube_published_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = :id",
        {"id": reel_db_id, "yt_id": youtube_video_id},
    )


async def mark_reel_published(reel_db_id: str, youtube_video_id: str) -> None:
    await execute(
        "UPDATE tiktok_reels SET status = 'published', youtube_video_id = :yt_id, "
        "youtube_published_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = :id",
        {"id": reel_db_id, "yt_id": youtube_video_id},
    )


async def mark_reel_failed(reel_db_id: str, error: str, increment_retry: bool = True) -> None:
    _set = "SET last_error = :error, status = 'failed', updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
    if increment_retry:
        _set += ", retry_count = retry_count + 1"
    await execute(
        f"UPDATE tiktok_reels {_set} WHERE id = :id",
        {"id": reel_db_id, "error": error},
    )


async def count_reels(source_id: str) -> int:
    res = await execute(
        "SELECT COUNT(*) as cnt FROM tiktok_reels WHERE source_id = :source_id",
        {"source_id": source_id},
    )
    return res.rows[0][0] if res.rows else 0


async def count_unpublished(source_id: str) -> int:
    res = await execute(
        "SELECT COUNT(*) as cnt FROM tiktok_reels "
        "WHERE source_id = :source_id AND status IN ('new', 'failed', 'error')",
        {"source_id": source_id},
    )
    return res.rows[0][0] if res.rows else 0


async def count_published(source_id: str) -> int:
    res = await execute(
        "SELECT COUNT(*) as cnt FROM tiktok_reels "
        "WHERE source_id = :source_id AND status = 'published'",
        {"source_id": source_id},
    )
    return res.rows[0][0] if res.rows else 0


async def claim_for_ai(reel_db_id: str) -> bool:
    """Claim a reel for AI metadata processing. Returns True if claimed."""
    res = await execute(
        "UPDATE tiktok_reels SET status = 'ai_pending', ai_claimed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = :id AND status = 'new'",
        {"id": reel_db_id},
    )
    return res.rows_affected > 0 if hasattr(res, "rows_affected") else False
