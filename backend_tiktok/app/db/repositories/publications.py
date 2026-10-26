from typing import Any

from ...db.client import execute, result_to_dict, result_to_dicts


async def create_publication(
    publication_id: str,
    reel_db_id: str,
    destination_id: str,
    status: str = "queued",
    **extra: Any,
) -> dict[str, Any]:
    cols = ["id", "reel_db_id", "destination_id", "status"]
    vals = [":id", ":reel_db_id", ":destination_id", ":status"]
    params: dict[str, Any] = {
        "id": publication_id,
        "reel_db_id": reel_db_id,
        "destination_id": destination_id,
        "status": status,
    }
    for key, val in extra.items():
        cols.append(key)
        vals.append(f":{key}")
        params[key] = val
    await execute(
        f"INSERT INTO tiktok_publications ({', '.join(cols)}) VALUES ({', '.join(vals)})",
        params,
    )
    row = await get_publication(publication_id)
    assert row is not None
    return row


async def get_publication(publication_id: str) -> dict[str, Any] | None:
    res = await execute(
        """
        SELECT id, reel_db_id, destination_id, status, youtube_video_id,
               youtube_title, youtube_description, youtube_hashtags_json,
               ai_model, started_at, published_at, last_error, retry_count,
               scheduled_publish_at, youtube_upload_mode, shorts_eligible,
               shorts_check_note, created_at, updated_at
        FROM tiktok_publications WHERE id = :id
        """,
        {"id": publication_id},
    )
    return result_to_dict(res)


async def list_publications(destination_id: str) -> list[dict[str, Any]]:
    res = await execute(
        """
        SELECT id, reel_db_id, destination_id, status, youtube_video_id,
               youtube_title, youtube_description, youtube_hashtags_json,
               ai_model, started_at, published_at, last_error, retry_count,
               scheduled_publish_at, youtube_upload_mode, shorts_eligible,
               shorts_check_note, created_at, updated_at
        FROM tiktok_publications WHERE destination_id = :destination_id
        ORDER BY created_at DESC
        """,
        {"destination_id": destination_id},
    )
    return result_to_dicts(res)


async def set_shorts_check(
    publication_id: str,
    shorts_eligible: bool | None,
    shorts_check_note: str | None,
) -> None:
    await execute(
        """
        UPDATE tiktok_publications
        SET shorts_eligible = :el, shorts_check_note = :note,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = :id
        """,
        {
            "id": publication_id,
            "el": None if shorts_eligible is None else (1 if shorts_eligible else 0),
            "note": shorts_check_note,
        },
    )


async def set_upload_mode(publication_id: str, mode: str) -> None:
    await execute(
        """
        UPDATE tiktok_publications
        SET youtube_upload_mode = :mode,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = :id
        """,
        {"id": publication_id, "mode": mode},
    )


async def list_publications_for_publish(batch_size: int = 20) -> list[dict[str, Any]]:
    res = await execute(
        """
        SELECT id, reel_db_id, destination_id, status, youtube_video_id,
               youtube_title, youtube_description, youtube_hashtags_json,
               ai_model, started_at, published_at, last_error, retry_count,
               scheduled_publish_at, created_at, updated_at
        FROM tiktok_publications
        WHERE status IN ('queued', 'processing', 'scheduled')
        AND last_error NOT LIKE 'CLAIM_LOST:%'
        ORDER BY created_at ASC
        LIMIT :limit
        """,
        {"limit": batch_size},
    )
    return result_to_dicts(res)


async def set_publication_ai_content(
    publication_id: str,
    youtube_title: str | None,
    youtube_description: str | None,
    youtube_hashtags_json: str | None,
    ai_model: str | None,
) -> None:
    await execute(
        """
        UPDATE tiktok_publications
        SET youtube_title = :title,
            youtube_description = :description,
            youtube_hashtags_json = :hashtags,
            ai_model = :model,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = :id
        """,
        {
            "id": publication_id,
            "title": youtube_title,
            "description": youtube_description,
            "hashtags": youtube_hashtags_json,
            "model": ai_model,
        },
    )


async def mark_scheduled(publication_id: str, youtube_video_id: str) -> None:
    await execute(
        """
        UPDATE tiktok_publications
        SET status = 'scheduled', youtube_video_id = :yt_id, started_at = :started_at,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = :id
        """,
        {"id": publication_id, "yt_id": youtube_video_id, "started_at": _now()},
    )


async def mark_published(
    publication_id: str, youtube_video_id: str, scheduled: bool = False
) -> None:
    status = "scheduled" if scheduled else "published"
    await execute(
        """
        UPDATE tiktok_publications
        SET status = :status, youtube_video_id = :yt_id,
            published_at = :published_at, last_error = NULL,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = :id
        """,
        {
            "id": publication_id,
            "status": status,
            "yt_id": youtube_video_id,
            "published_at": _now(),
        },
    )


async def mark_failed(publication_id: str, error: str) -> None:
    await execute(
        """
        UPDATE tiktok_publications
        SET status = 'failed', last_error = :error, retry_count = retry_count + 1,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = :id
        """,
        {"id": publication_id, "error": error},
    )


async def set_publication_status(publication_id: str, status: str) -> None:
    await execute(
        "UPDATE tiktok_publications SET status = :status, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = :id",
        {"id": publication_id, "status": status},
    )


async def set_scheduled_publish_at(publication_id: str, scheduled_at: str) -> None:
    await execute(
        "UPDATE tiktok_publications SET scheduled_publish_at = :scheduled_at, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {"id": publication_id, "scheduled_at": scheduled_at},
    )


def _now() -> str:
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
