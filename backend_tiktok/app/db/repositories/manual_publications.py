from typing import Any

from ...db.client import execute, result_to_dict, result_to_dicts


async def create_manual_publication(
    pub_id: str,
    destination_id: str,
    pipeline_id: str,
    source_url: str,
    source_hash: str,
    caption: str | None = None,
    youtube_title: str | None = None,
    youtube_description: str | None = None,
    youtube_hashtags_json: str | None = None,
    visibility: str = "public",
    publish_at: str | None = None,
) -> dict[str, Any]:
    await execute(
        """
        INSERT INTO tiktok_manual_publications
            (id, destination_id, pipeline_id, source_url, source_hash, caption,
             youtube_title, youtube_description, youtube_hashtags_json,
             visibility, publish_at)
        VALUES
            (:id, :destination_id, :pipeline_id, :source_url, :source_hash, :caption,
             :youtube_title, :youtube_description, :youtube_hashtags_json,
             :visibility, :publish_at)
        """,
        {
            "id": pub_id,
            "destination_id": destination_id,
            "pipeline_id": pipeline_id,
            "source_url": source_url,
            "source_hash": source_hash,
            "caption": caption,
            "youtube_title": youtube_title,
            "youtube_description": youtube_description,
            "youtube_hashtags_json": youtube_hashtags_json,
            "visibility": visibility,
            "publish_at": publish_at,
        },
    )
    return await get_manual_publication(pub_id)  # type: ignore[return-value]


async def get_manual_publication(pub_id: str) -> dict[str, Any] | None:
    res = await execute(
        """
        SELECT id, destination_id, pipeline_id, source_url, source_hash, caption,
               thumbnail_url, duration, youtube_title, youtube_description,
               youtube_hashtags_json, visibility, publish_at, status, stage,
               youtube_video_id, error_code, error, retry_count,
               created_at, started_at, completed_at, updated_at
        FROM tiktok_manual_publications WHERE id = :id
        """,
        {"id": pub_id},
    )
    return result_to_dict(res)


async def list_manual_publications(
    destination_id: str | None = None, status: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: dict[str, Any] = {"limit": limit}
    if destination_id:
        where.append("destination_id = :destination_id")
        params["destination_id"] = destination_id
    if status:
        where.append("status = :status")
        params["status"] = status
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    res = await execute(
        f"""
        SELECT id, destination_id, pipeline_id, source_url, source_hash, caption,
               thumbnail_url, duration, youtube_title, youtube_description,
               youtube_hashtags_json, visibility, publish_at, status, stage,
               youtube_video_id, error_code, error, retry_count,
               created_at, started_at, completed_at, updated_at
        FROM tiktok_manual_publications
        {where_sql}
        ORDER BY created_at DESC
        LIMIT :limit
        """,
        params,
    )
    return result_to_dicts(res)


async def set_manual_pub_status(pub_id: str, status: str, stage: str | None = None) -> None:
    sets = ["status = :status", "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"]
    params: dict[str, Any] = {"id": pub_id, "status": status}
    if status == "processing":
        sets.append("started_at = COALESCE(started_at, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))")
    if stage is not None:
        sets.append("stage = :stage")
        params["stage"] = stage
    await execute(
        f"UPDATE tiktok_manual_publications SET {', '.join(sets)} WHERE id = :id",
        params,
    )


async def set_manual_pub_started(pub_id: str) -> None:
    await execute(
        "UPDATE tiktok_manual_publications SET started_at = COALESCE(started_at, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')), updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {"id": pub_id},
    )


async def set_manual_pub_media(
    pub_id: str,
    thumbnail_url: str | None,
    duration: float | None,
    youtube_title: str | None,
    youtube_description: str | None,
    youtube_hashtags_json: str | None,
    caption: str | None,
) -> None:
    await execute(
        """
        UPDATE tiktok_manual_publications
        SET thumbnail_url = :thumbnail_url,
            duration = :duration,
            youtube_title = COALESCE(:youtube_title, youtube_title),
            youtube_description = COALESCE(:youtube_description, youtube_description),
            youtube_hashtags_json = COALESCE(:hashtags, youtube_hashtags_json),
            caption = COALESCE(:caption, caption),
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = :id
        """,
        {
            "id": pub_id,
            "thumbnail_url": thumbnail_url,
            "duration": duration,
            "youtube_title": youtube_title,
            "youtube_description": youtube_description,
            "hashtags": youtube_hashtags_json,
            "caption": caption,
        },
    )


async def mark_manual_pub_error(
    pub_id: str, error: str, retry_increment: bool = True
) -> None:
    set_clause = "error = :error, retry_count = retry_count + 1" if retry_increment else "error = :error"
    await execute(
        f"UPDATE tiktok_manual_publications SET {set_clause}, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {"id": pub_id, "error": error},
    )


async def set_manual_pub_yt_video(
    pub_id: str, youtube_video_id: str
) -> None:
    await execute(
        """
        UPDATE tiktok_manual_publications
        SET youtube_video_id = :yt_id,
            completed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = :id
        """,
        {"id": pub_id, "yt_id": youtube_video_id},
    )


async def find_manual_pub_by_hash(destination_id: str, source_hash: str) -> dict[str, Any] | None:
    res = await execute(
        """
        SELECT id, destination_id, pipeline_id, source_url, source_hash, caption,
               thumbnail_url, duration, youtube_title, youtube_description,
               youtube_hashtags_json, visibility, publish_at, status, stage,
               youtube_video_id, error_code, error, retry_count,
               created_at, started_at, completed_at, updated_at
        FROM tiktok_manual_publications
        WHERE destination_id = :dest_id AND source_hash = :source_hash
        ORDER BY created_at DESC
        LIMIT 1
        """,
        {"dest_id": destination_id, "source_hash": source_hash},
    )
    return result_to_dict(res)
