"""Manual Facebook -> YouTube publications. Separate from inventory/reels.

A manual publication references a Facebook source URL directly — no
facebook_reels row is ever created for it, so the auto pipeline
(inventory, scheduler, AI worker) is completely untouched.
"""

import hashlib
import uuid
from typing import Any

from ..client import get_client

_COLUMNS = (
    "id, destination_id, pipeline_id, source_url, source_hash, caption, "
    "thumbnail_url, duration, youtube_title, youtube_description, "
    "youtube_hashtags_json, visibility, publish_at, status, stage, "
    "youtube_video_id, error_code, error, retry_count, created_at, "
    "started_at, completed_at, updated_at"
)

_TERMINAL_DUPLICATE_STATUSES = ("queued", "processing", "scheduled", "published")


def canonical_source_url(url: str) -> str:
    """Normalize for duplicate detection: strip, lowercase, no trailing slash."""
    return (url or "").strip().rstrip("/").lower()


def source_hash(url: str) -> str:
    return hashlib.sha256(canonical_source_url(url).encode("utf-8")).hexdigest()


def _row_to_dict(r: Any) -> dict[str, Any]:
    import json as _json

    try:
        hashtags = _json.loads(r[10]) if r[10] else []
    except Exception:
        hashtags = []
    return {
        "id": r[0],
        "destination_id": r[1],
        "pipeline_id": r[2],
        "source_url": r[3],
        "source_hash": r[4],
        "caption": r[5],
        "thumbnail_url": r[6],
        "duration": r[7],
        "youtube_title": r[8],
        "youtube_description": r[9],
        "youtube_hashtags": hashtags if isinstance(hashtags, list) else [],
        "visibility": r[11] or "public",
        "publish_at": r[12],
        "status": r[13],
        "stage": r[14],
        "youtube_video_id": r[15],
        "error_code": r[16],
        "error": r[17],
        "retry_count": r[18] or 0,
        "created_at": r[19],
        "started_at": r[20],
        "completed_at": r[21],
        "updated_at": r[22],
    }


def to_safe_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Public API shape. Manual rows hold no credentials or download URLs."""
    return {
        "id": row["id"],
        "destination_id": row["destination_id"],
        "pipeline_id": row.get("pipeline_id"),
        "pipeline_name": row.get("pipeline_name"),
        "channel_id": row.get("channel_id"),
        "channel_name": row.get("channel_name"),
        "source_url": row.get("source_url"),
        "caption": row.get("caption"),
        "thumbnail_url": row.get("thumbnail_url"),
        "duration": row.get("duration"),
        "youtube_title": row.get("youtube_title"),
        "youtube_description": row.get("youtube_description"),
        "youtube_hashtags": row.get("youtube_hashtags", []),
        "visibility": row.get("visibility", "public"),
        "publish_at": row.get("publish_at"),
        "status": row.get("status"),
        "stage": row.get("stage"),
        "youtube_video_id": row.get("youtube_video_id"),
        "youtube_url": (
            f"https://www.youtube.com/watch?v={row['youtube_video_id']}"
            if row.get("youtube_video_id")
            else None
        ),
        "error_code": row.get("error_code"),
        "error": row.get("error"),
        "retry_count": row.get("retry_count", 0),
        "created_at": row.get("created_at"),
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
    }


async def create_manual_publication(
    *,
    destination_id: str,
    pipeline_id: str,
    source_url: str,
    caption: str | None = None,
    thumbnail_url: str | None = None,
    duration: float | None = None,
    title: str,
    description: str,
    hashtags: list[str] | None = None,
    visibility: str = "public",
    publish_at: str | None = None,
) -> dict[str, Any]:
    import json as _json

    client = get_client()
    manual_id = f"mpub_{uuid.uuid4().hex[:12]}"
    await client.execute(
        """
        INSERT INTO facebook_manual_publications
        (id, destination_id, pipeline_id, source_url, source_hash, caption,
         thumbnail_url, duration, youtube_title, youtube_description,
         youtube_hashtags_json, visibility, publish_at, status, stage)
        VALUES (:id, :destination_id, :pipeline_id, :source_url, :source_hash,
         :caption, :thumbnail_url, :duration, :title, :description,
         :hashtags, :visibility, :publish_at, 'queued', 'queued')
        """,
        {
            "id": manual_id,
            "destination_id": destination_id,
            "pipeline_id": pipeline_id,
            "source_url": source_url.strip(),
            "source_hash": source_hash(source_url),
            "caption": caption,
            "thumbnail_url": thumbnail_url,
            "duration": duration,
            "title": title,
            "description": description,
            "hashtags": _json.dumps(hashtags or []),
            "visibility": visibility,
            "publish_at": publish_at,
        },
    )
    row = await get_manual_publication(manual_id)
    assert row is not None
    return row


async def get_manual_publication(manual_id: str) -> dict[str, Any] | None:
    client = get_client()
    rows = await client.execute(
        f"SELECT {_COLUMNS} FROM facebook_manual_publications WHERE id = :id",
        {"id": manual_id},
    )
    if not rows.rows:
        return None
    return _row_to_dict(rows.rows[0])


async def find_duplicate(destination_id: str, source_url: str) -> dict[str, Any] | None:
    """A non-failed manual publication for the same channel+URL blocks repost
    unless the caller passes force_duplicate. Failed rows never block."""
    client = get_client()
    placeholders = ",".join(f":s{i}" for i in range(len(_TERMINAL_DUPLICATE_STATUSES)))
    rows = await client.execute(
        f"SELECT {_COLUMNS} FROM facebook_manual_publications "
        "WHERE destination_id = :destination_id AND source_hash = :source_hash "
        f"AND status IN ({placeholders}) ORDER BY created_at DESC LIMIT 1",
        {
            "destination_id": destination_id,
            "source_hash": source_hash(source_url),
            **{f"s{i}": s for i, s in enumerate(_TERMINAL_DUPLICATE_STATUSES)},
        },
    )
    if not rows.rows:
        return None
    return _row_to_dict(rows.rows[0])


async def list_manual_publications(
    *, destination_id: str | None = None, limit: int = 50, offset: int = 0
) -> tuple[list[dict[str, Any]], int]:
    """Newest first, enriched with channel + pipeline names for the UI."""
    client = get_client()
    where = ""
    params: dict[str, Any] = {}
    if destination_id:
        where = "WHERE m.destination_id = :destination_id"
        params["destination_id"] = destination_id
    total_rows = await client.execute(
        f"SELECT COUNT(*) FROM facebook_manual_publications m {where}", params
    )
    total = total_rows.rows[0][0] if total_rows.rows else 0
    rows = await client.execute(
        "SELECT m.id, m.destination_id, m.pipeline_id, m.source_url, m.source_hash, "
        "m.caption, m.thumbnail_url, m.duration, m.youtube_title, m.youtube_description, "
        "m.youtube_hashtags_json, m.visibility, m.publish_at, m.status, m.stage, "
        "m.youtube_video_id, m.error_code, m.error, m.retry_count, m.created_at, "
        "m.started_at, m.completed_at, m.updated_at, "
        "d.channel_id, d.channel_name, p.name "
        "FROM facebook_manual_publications m "
        "LEFT JOIN youtube_destinations d ON d.id = m.destination_id "
        "LEFT JOIN facebook_pipelines p ON p.id = m.pipeline_id "
        f"{where} ORDER BY m.created_at DESC, m.id DESC LIMIT :limit OFFSET :offset",
        {**params, "limit": max(1, min(limit, 100)), "offset": max(0, offset)},
    )
    items = []
    for r in rows.rows or []:
        row = _row_to_dict(r[:23])
        row["channel_id"] = r[23]
        row["channel_name"] = r[24]
        row["pipeline_name"] = r[25]
        items.append(to_safe_dict(row))
    return items, total


async def claim_next_manual_job() -> dict[str, Any] | None:
    """Atomically claim the oldest queued manual job (highest priority first).
    Shares the publisher loop's single semaphore with auto jobs, so heavy
    publishing never runs in parallel. Manual jobs are claimed before auto
    jobs by the loop (slightly higher priority), never alongside them.
    """
    from datetime import datetime, timezone

    client = get_client()
    rows = await client.execute(
        f"SELECT {_COLUMNS} FROM facebook_manual_publications "
        "WHERE status = 'queued' ORDER BY created_at ASC, id ASC LIMIT 1"
    )
    if not rows.rows:
        return None
    job = _row_to_dict(rows.rows[0])
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        res = await client.execute(
            "UPDATE facebook_manual_publications SET status = 'processing', "
            "stage = 'claimed', started_at = :now, updated_at = :now "
            "WHERE id = :id AND status = 'queued'",
            {"id": job["id"], "now": now_iso},
        )
    except Exception:
        return None
    if (res.rows_affected or 0) == 0:
        return None
    job["status"] = "processing"
    return job


async def set_stage(manual_id: str, stage: str) -> None:
    client = get_client()
    await client.execute(
        "UPDATE facebook_manual_publications SET stage = :stage, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {"stage": stage, "id": manual_id},
    )


async def mark_processing(manual_id: str) -> None:
    await set_stage(manual_id, "processing")


async def mark_scheduled(manual_id: str, youtube_video_id: str) -> None:
    client = get_client()
    await client.execute(
        "UPDATE facebook_manual_publications SET status = 'scheduled', stage = 'completed', "
        "youtube_video_id = :vid, error_code = NULL, error = NULL, "
        "completed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {"vid": youtube_video_id, "id": manual_id},
    )


async def mark_published(manual_id: str, youtube_video_id: str) -> None:
    client = get_client()
    await client.execute(
        "UPDATE facebook_manual_publications SET status = 'published', stage = 'completed', "
        "youtube_video_id = :vid, error_code = NULL, error = NULL, "
        "completed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {"vid": youtube_video_id, "id": manual_id},
    )


async def mark_failed(manual_id: str, error_code: str, error: str) -> None:
    client = get_client()
    await client.execute(
        "UPDATE facebook_manual_publications SET status = 'failed', stage = 'failed', "
        "error_code = :code, error = :error, "
        "retry_count = retry_count + 1, "
        "completed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {"code": (error_code or "FAILED")[:64], "error": (error or "")[:2000], "id": manual_id},
    )


async def retry_manual(manual_id: str) -> dict[str, Any] | None:
    """Requeue a failed (or stuck) manual publication. Returns updated row."""
    client = get_client()
    res = await client.execute(
        "UPDATE facebook_manual_publications SET status = 'queued', stage = 'queued', "
        "error_code = NULL, error = NULL, started_at = NULL, completed_at = NULL, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = :id AND status IN ('failed', 'queued')",
        {"id": manual_id},
    )
    if (res.rows_affected or 0) == 0:
        return None
    return await get_manual_publication(manual_id)


async def count_active_for_destination(destination_id: str) -> int:
    """Live (queued/processing) manual publications for one destination."""
    client = get_client()
    rows = await client.execute(
        "SELECT COUNT(*) FROM facebook_manual_publications "
        "WHERE destination_id = :id AND status IN ('queued', 'processing')",
        {"id": destination_id},
    )
    return rows.rows[0][0] if rows.rows else 0
