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


_REEL_COLUMNS = (
    "r.id, r.source_id, r.reel_id, r.reel_url, r.caption, r.thumbnail_url, "
    "r.source_published_at, r.discovered_at, r.status, r.retry_count, r.last_error, "
    "r.youtube_video_id, r.youtube_published_at, r.created_at, r.updated_at"
)


def _reel_to_dict(r: Any) -> dict[str, Any]:
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


def _pipeline_scope(pipeline_id: str) -> str:
    return "r.source_id IN (SELECT id FROM facebook_sources WHERE pipeline_id = :pipeline_id)"


async def list_inventory(
    pipeline_id: str,
    *,
    status: str | None = None,
    source_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """(items, total) for a pipeline. Single data query + single count query."""
    client = get_client()
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    conds = [_pipeline_scope(pipeline_id)]
    params: dict[str, Any] = {"pipeline_id": pipeline_id, "limit": limit, "offset": offset}
    if status:
        conds.append("r.status = :status")
        params["status"] = status
    if source_id:
        conds.append("r.source_id = :source_id")
        params["source_id"] = source_id
    where = " AND ".join(conds)
    rows = await client.execute(
        f"SELECT {_REEL_COLUMNS} FROM facebook_reels r WHERE {where} "
        "ORDER BY r.discovered_at DESC, r.id LIMIT :limit OFFSET :offset",
        params,
    )
    total_rows = await client.execute(
        f"SELECT COUNT(*) FROM facebook_reels r WHERE {where}",
        {k: v for k, v in params.items() if k not in ("limit", "offset")},
    )
    total = total_rows.rows[0][0] if total_rows.rows else 0
    return [_reel_to_dict(r) for r in rows.rows], total


async def inventory_stats(pipeline_id: str) -> dict[str, int]:
    """Single GROUP BY query: per-status counts + totals. No N+1."""
    client = get_client()
    rows = await client.execute(
        "SELECT r.status, COUNT(*) FROM facebook_reels r "
        f"WHERE {_pipeline_scope(pipeline_id)} GROUP BY r.status",
        {"pipeline_id": pipeline_id},
    )
    by_status = {r[0]: r[1] for r in (rows.rows or [])}
    total = sum(by_status.values())
    published = by_status.get("published", 0)
    return {
        "total": total,
        "new": by_status.get("new", 0),
        "queued": by_status.get("queued", 0),
        "processing": by_status.get("processing", 0),
        "published": published,
        "failed": by_status.get("failed", 0),
        "skipped": by_status.get("skipped", 0),
        "unpublished": total - published,
    }


async def select_next_unpublished_reel(pipeline_id: str) -> dict[str, Any] | None:
    """Newest unpublished reel: status=new, freshest source_published_at first.

    Fresh scans naturally win; with no fresh reels this falls back to older
    stored new reels. Deterministic tie-break on id.
    """
    client = get_client()
    rows = await client.execute(
        f"SELECT {_REEL_COLUMNS} FROM facebook_reels r "
        f"WHERE {_pipeline_scope(pipeline_id)} AND r.status = 'new' "
        "ORDER BY r.source_published_at DESC NULLS LAST, r.discovered_at DESC, r.id ASC LIMIT 1",
        {"pipeline_id": pipeline_id},
    )
    if not rows.rows:
        return None
    return _reel_to_dict(rows.rows[0])


async def claim_next_reel(
    pipeline_id: str, *, max_attempts: int = 5
) -> tuple[dict[str, Any] | None, bool]:
    """Atomically claim one new reel (new -> queued).

    Conditional UPDATE + rows_affected check; on contention retry with the
    next candidate. Returns (reel, True) or (None, False) when empty.
    """
    client = get_client()
    tried: set[str] = set()
    for _ in range(max(1, max_attempts)):
        params: dict[str, Any] = {"pipeline_id": pipeline_id}
        skip = ""
        if tried:
            skip = "AND r.id NOT IN (" + ",".join(f":skip{i}" for i in range(len(tried))) + ")"
            for i, rid in enumerate(sorted(tried)):
                params[f"skip{i}"] = rid
        rows = await client.execute(
            f"SELECT {_REEL_COLUMNS} FROM facebook_reels r "
            f"WHERE {_pipeline_scope(pipeline_id)} AND r.status = 'new' {skip} "
            "ORDER BY r.source_published_at DESC NULLS LAST, r.discovered_at DESC, r.id ASC LIMIT 1",
            params,
        )
        if not rows.rows:
            return None, False
        candidate = _reel_to_dict(rows.rows[0])
        res = await client.execute(
            "UPDATE facebook_reels SET status = 'queued', "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
            "WHERE id = :id AND status = 'new'",
            {"id": candidate["id"]},
        )
        if (res.rows_affected or 0) > 0:
            candidate["status"] = "queued"
            return candidate, True
        tried.add(candidate["id"])
    return None, False


async def release_claim(reel_db_id: str) -> bool:
    """queued -> new only. Rejects published/processing. Returns True if released."""
    client = get_client()
    res = await client.execute(
        "UPDATE facebook_reels SET status = 'new', "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = :id AND status = 'queued'",
        {"id": reel_db_id},
    )
    return (res.rows_affected or 0) > 0


async def recover_stale_queued(max_age_minutes: int = 120) -> int:
    """Reset old queued claims to new. Never touches processing/published."""
    client = get_client()
    res = await client.execute(
        "UPDATE facebook_reels SET status = 'new', "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE status = 'queued' AND updated_at < "
        "strftime('%Y-%m-%dT%H:%M:%SZ', 'now', :cutoff)",
        {"cutoff": f"-{max(1, max_age_minutes)} minutes"},
    )
    return res.rows_affected or 0
