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
        "previous_status, created_at, updated_at FROM tiktok_reels WHERE id = :id",
        {"id": reel_db_id},
    )
    return result_to_dict(res)


async def list_reels(source_id: str, status: str | None = None) -> list[dict[str, Any]]:
    if status:
        res = await execute(
            "SELECT id, source_id, reel_id, reel_url, caption, thumbnail_url, "
            "source_published_at, duration, play_count, discovered_at, status, "
            "retry_count, last_error, youtube_video_id, youtube_published_at, "
            "previous_status, created_at, updated_at FROM tiktok_reels WHERE source_id = :source_id "
            "AND status = :status ORDER BY discovered_at DESC",
            {"source_id": source_id, "status": status},
        )
    else:
        res = await execute(
            "SELECT id, source_id, reel_id, reel_url, caption, thumbnail_url, "
            "source_published_at, duration, play_count, discovered_at, status, "
            "retry_count, last_error, youtube_video_id, youtube_published_at, "
            "previous_status, created_at, updated_at FROM tiktok_reels WHERE source_id = :source_id "
            "ORDER BY discovered_at DESC",
            {"source_id": source_id},
        )
    return result_to_dicts(res)


async def list_unpublished_reels(source_id: str, limit: int = 50) -> list[dict[str, Any]]:
    res = await execute(
        "SELECT id, source_id, reel_id, reel_url, caption, thumbnail_url, "
        "source_published_at, duration, play_count, discovered_at, status, "
        "retry_count, last_error, youtube_video_id, youtube_published_at, "
        "previous_status, created_at, updated_at FROM tiktok_reels "
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


async def count_excluded(source_id: str) -> int:
    res = await execute(
        "SELECT COUNT(*) as cnt FROM tiktok_reels "
        "WHERE source_id = :source_id AND status = 'excluded'",
        {"source_id": source_id},
    )
    return res.rows[0][0] if res.rows else 0


async def get_reel_pipeline(reel_db_id: str) -> dict[str, Any] | None:
    """Get reel details along with source and pipeline information."""
    res = await execute(
        """
        SELECT r.id, r.source_id, r.reel_id, r.reel_url, r.caption, r.thumbnail_url,
               r.source_published_at, r.duration, r.play_count, r.discovered_at, r.status,
               r.retry_count, r.last_error, r.youtube_video_id, r.youtube_published_at,
               r.previous_status, r.created_at, r.updated_at,
               s.pipeline_id, s.username as source_username
        FROM tiktok_reels r
        JOIN tiktok_sources s ON s.id = r.source_id
        WHERE r.id = :id
        """,
        {"id": reel_db_id},
    )
    return result_to_dict(res)


async def check_reel_busy(reel_db_id: str) -> tuple[bool, str | None]:
    """Check if a reel is actively being processed/published or claimed.

    Returns (is_busy, reason).
    """
    row = await get_reel(reel_db_id)
    if not row:
        return (False, None)

    if row.get("status") in ("processing", "ai_pending"):
        return (True, f"Video đang ở trạng thái '{row.get('status')}'")

    # Check publish queue
    q_res = await execute(
        "SELECT id, status, stage FROM tiktok_publish_queue WHERE reel_db_id = :id AND status = 'processing'",
        {"id": reel_db_id},
    )
    if q_res.rows:
        return (True, "Video đang được đăng lên YouTube (hàng đợi processing)")

    # Check publications
    pub_res = await execute(
        "SELECT id, status FROM tiktok_publications WHERE reel_db_id = :id AND status = 'processing'",
        {"id": reel_db_id},
    )
    if pub_res.rows:
        return (True, "Video đang trong quá trình xuất bản")

    return (False, None)


async def exclude_reel(reel_db_id: str, pipeline_id: str | None = None) -> dict[str, Any]:
    """Exclude a reel from inventory.

    Validates pipeline ownership, checks processing status, cancels queued jobs,
    and updates reel status to 'excluded' while preserving previous_status and publication history.
    """
    info = await get_reel_pipeline(reel_db_id)
    if not info:
        return {"ok": False, "error_code": "NOT_FOUND", "message": "Video không tồn tại trong kho."}

    if pipeline_id and info.get("pipeline_id") != pipeline_id:
        return {"ok": False, "error_code": "PIPELINE_MISMATCH", "message": "Video không thuộc Pipeline này."}

    is_busy, busy_reason = await check_reel_busy(reel_db_id)
    if is_busy:
        return {"ok": False, "error_code": "PROCESSING", "message": busy_reason or "Video đang được xử lý, không thể xóa."}

    if info.get("status") == "excluded":
        return {"ok": True, "reel_id": reel_db_id, "status": "excluded", "message": "Video đã ở trạng thái loại trừ."}

    # Cancel any queued publish jobs for this reel
    await execute(
        """
        UPDATE tiktok_publish_queue
        SET status = 'cancelled', stage = 'cancelled',
            error = 'Đã hủy do video bị loại bỏ khỏi kho (excluded)',
            finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE reel_db_id = :id AND status = 'queued'
        """,
        {"id": reel_db_id},
    )

    # Cancel non-terminal publications for this reel
    await execute(
        """
        UPDATE tiktok_publications
        SET status = 'cancelled',
            last_error = 'Đã hủy do video bị loại bỏ khỏi kho (excluded)',
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE reel_db_id = :id AND status IN ('draft', 'queued', 'scheduled')
        """,
        {"id": reel_db_id},
    )

    # Update reel status to 'excluded', recording previous_status
    curr_status = info.get("status") or "new"
    await execute(
        """
        UPDATE tiktok_reels
        SET previous_status = :prev_status,
            status = 'excluded',
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = :id
        """,
        {"id": reel_db_id, "prev_status": curr_status},
    )

    updated = await get_reel(reel_db_id)
    return {
        "ok": True,
        "reel_id": reel_db_id,
        "pipeline_id": info.get("pipeline_id"),
        "status": "excluded",
        "previous_status": curr_status,
        "reel": updated,
    }


async def restore_reel(reel_db_id: str, pipeline_id: str | None = None) -> dict[str, Any]:
    """Restore an excluded reel back to active inventory."""
    info = await get_reel_pipeline(reel_db_id)
    if not info:
        return {"ok": False, "error_code": "NOT_FOUND", "message": "Video không tồn tại trong kho."}

    if pipeline_id and info.get("pipeline_id") != pipeline_id:
        return {"ok": False, "error_code": "PIPELINE_MISMATCH", "message": "Video không thuộc Pipeline này."}

    if info.get("status") != "excluded":
        return {
            "ok": False,
            "error_code": "NOT_EXCLUDED",
            "message": f"Chỉ có thể khôi phục video đang bị loại trừ (trạng thái hiện tại: {info.get('status')}).",
        }

    # Restore to previous_status or 'new'
    target_status = info.get("previous_status") or "new"
    if target_status == "excluded":
        target_status = "new"

    await execute(
        """
        UPDATE tiktok_reels
        SET status = :target_status,
            previous_status = NULL,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = :id AND status = 'excluded'
        """,
        {"id": reel_db_id, "target_status": target_status},
    )

    updated = await get_reel(reel_db_id)
    return {
        "ok": True,
        "reel_id": reel_db_id,
        "pipeline_id": info.get("pipeline_id"),
        "status": target_status,
        "reel": updated,
    }


async def bulk_exclude_reels(pipeline_id: str, reel_db_ids: list[str]) -> dict[str, Any]:
    """Bulk exclude reels belonging to a specific pipeline."""
    if not reel_db_ids:
        return {"ok": True, "excluded": 0, "rejected": [], "unchanged": 0}

    excluded_count = 0
    rejected: list[dict[str, Any]] = []

    for rid in reel_db_ids:
        res = await exclude_reel(rid, pipeline_id=pipeline_id)
        if res.get("ok"):
            excluded_count += 1
        else:
            rejected.append({"reel_id": rid, "reason": res.get("message") or res.get("error_code")})

    return {
        "ok": True,
        "excluded": excluded_count,
        "rejected": rejected,
        "total_requested": len(reel_db_ids),
    }


async def bulk_restore_reels(pipeline_id: str, reel_db_ids: list[str]) -> dict[str, Any]:
    """Bulk restore reels belonging to a specific pipeline."""
    if not reel_db_ids:
        return {"ok": True, "restored": 0, "rejected": []}

    restored_count = 0
    rejected: list[dict[str, Any]] = []

    for rid in reel_db_ids:
        res = await restore_reel(rid, pipeline_id=pipeline_id)
        if res.get("ok"):
            restored_count += 1
        else:
            rejected.append({"reel_id": rid, "reason": res.get("message") or res.get("error_code")})

    return {
        "ok": True,
        "restored": restored_count,
        "rejected": rejected,
        "total_requested": len(reel_db_ids),
    }


async def list_reels_for_pipeline(pipeline_id: str, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    if status:
        res = await execute(
            """
            SELECT r.id, r.source_id, r.reel_id, r.reel_url, r.caption, r.thumbnail_url,
                   r.source_published_at, r.duration, r.play_count, r.discovered_at, r.status,
                   r.retry_count, r.last_error, r.youtube_video_id, r.youtube_published_at,
                   r.previous_status, r.created_at, r.updated_at,
                   s.username as source_username
            FROM tiktok_reels r
            JOIN tiktok_sources s ON s.id = r.source_id
            WHERE s.pipeline_id = :pid AND r.status = :status
            ORDER BY r.discovered_at DESC LIMIT :limit
            """,
            {"pid": pipeline_id, "status": status, "limit": limit},
        )
    else:
        res = await execute(
            """
            SELECT r.id, r.source_id, r.reel_id, r.reel_url, r.caption, r.thumbnail_url,
                   r.source_published_at, r.duration, r.play_count, r.discovered_at, r.status,
                   r.retry_count, r.last_error, r.youtube_video_id, r.youtube_published_at,
                   r.previous_status, r.created_at, r.updated_at,
                   s.username as source_username
            FROM tiktok_reels r
            JOIN tiktok_sources s ON s.id = r.source_id
            WHERE s.pipeline_id = :pid
            ORDER BY r.discovered_at DESC LIMIT :limit
            """,
            {"pid": pipeline_id, "limit": limit},
        )
    return result_to_dicts(res)
