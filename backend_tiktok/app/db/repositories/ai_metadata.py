import json
from typing import Any

from ...db.client import execute, result_to_dict, result_to_dicts


async def get_metadata(reel_db_id: str) -> dict[str, Any] | None:
    res = await execute(
        "SELECT reel_db_id, title, description, hashtags_json, model, status, "
        "source_hash, generated_at, last_error, retry_count, next_retry_at, "
        "config_hash, created_at, updated_at "
        "FROM tiktok_ai_metadata WHERE reel_db_id = :id",
        {"id": reel_db_id},
    )
    return result_to_dict(res)


async def create_metadata_entry(reel_db_id: str, source_hash: str) -> None:
    await execute(
        "INSERT OR IGNORE INTO tiktok_ai_metadata (reel_db_id, source_hash, status) VALUES (:id, :sh, 'pending')",
        {"id": reel_db_id, "sh": source_hash},
    )


async def set_pending(reel_db_id: str, source_hash: str) -> None:
    await execute(
        "UPDATE tiktok_ai_metadata SET status = 'pending', source_hash = :sh, "
        "last_error = NULL, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE reel_db_id = :id",
        {"id": reel_db_id, "sh": source_hash},
    )


async def mark_claimed(reel_db_id: str, model: str) -> bool:
    now = _now_iso()
    res = await execute(
        "UPDATE tiktok_ai_metadata SET status = 'processing', model = :model, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE reel_db_id = :id AND status = 'pending'",
        {"id": reel_db_id, "model": model},
    )
    return res.rows_affected > 0 if hasattr(res, "rows_affected") else False


async def mark_success(
    reel_db_id: str,
    title: str | None,
    description: str | None,
    hashtags: list[str] | None,
    model: str,
    config_hash: str,
) -> None:
    await execute(
        """
        UPDATE tiktok_ai_metadata
        SET status = 'ready', title = :title, description = :description,
            hashtags_json = :hashtags, model = :model,
            generated_at = :now, config_hash = :chash,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE reel_db_id = :id
        """,
        {
            "id": reel_db_id,
            "title": title,
            "description": description,
            "hashtags": json.dumps(hashtags or []),
            "model": model,
            "now": now,
            "chash": config_hash,
        },
    )


async def mark_failed(reel_db_id: str, error: str, retry_at: str | None = None, config_hash: str | None = None) -> None:
    await execute(
        """
        UPDATE tiktok_ai_metadata
        SET status = 'failed', last_error = :err, retry_count = retry_count + 1,
            next_retry_at = :retry_at, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE reel_db_id = :id
        """,
        {"id": reel_db_id, "err": error, "retry_at": retry_at or _now_iso()},
    )


async def list_ready_for_claim(limit: int = 10) -> list[dict[str, Any]]:
    res = await execute(
        """
        SELECT reel_db_id, title, description, hashtags_json, model, status,
               source_hash, generated_at, last_error, retry_count, next_retry_at,
               config_hash, created_at, updated_at
        FROM tiktok_ai_metadata
        WHERE status = 'ready' AND (next_retry_at IS NULL OR next_retry_at <= :now)
        ORDER BY created_at ASC
        LIMIT :limit
        """,
        {"now": _now_iso(), "limit": limit},
    )
    return result_to_dicts(res)


async def list_stale_for_retry(limit: int = 10) -> list[dict[str, Any]]:
    res = await execute(
        """
        SELECT reel_db_id, title, description, hashtags_json, model, status,
               source_hash, generated_at, last_error, retry_count, next_retry_at,
               config_hash, created_at, updated_at
        FROM tiktok_ai_metadata
        WHERE status IN ('pending', 'failed') AND next_retry_at <= :now
        ORDER BY next_retry_at ASC
        LIMIT :limit
        """,
        {"now": _now_iso(), "limit": limit},
    )
    return result_to_dicts(res)


def _now_iso() -> str:
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
