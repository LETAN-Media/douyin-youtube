from datetime import datetime, timezone
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
        "SELECT r.id, r.source_id, r.reel_id, r.reel_url, r.caption, r.thumbnail_url, "
        "r.source_published_at, r.discovered_at, r.status, r.retry_count, r.last_error, "
        "r.youtube_video_id, r.youtube_published_at, r.created_at, r.updated_at, "
        "s.pipeline_id "
        "FROM facebook_reels r "
        "LEFT JOIN facebook_sources s ON s.id = r.source_id "
        "WHERE r.id = :id",
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
        "pipeline_id": r[15] if len(r) > 15 else None,
    }


async def get_reel_pipeline_id(reel_db_id: str) -> str | None:
    client = get_client()
    rows = await client.execute(
        "SELECT s.pipeline_id FROM facebook_reels r "
        "JOIN facebook_sources s ON s.id = r.source_id "
        "WHERE r.id = :id",
        {"id": reel_db_id},
    )
    if rows.rows and rows.rows[0][0]:
        return str(rows.rows[0][0])
    return None


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


async def advance_status(reel_db_id: str, from_status: str, to_status: str) -> bool:
    """Conditional transition. Returns True only if the row was in from_status."""
    client = get_client()
    res = await client.execute(
        "UPDATE facebook_reels SET status = :to_status, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = :id AND status = :from_status",
        {"to_status": to_status, "from_status": from_status, "id": reel_db_id},
    )
    return (res.rows_affected or 0) > 0


async def release_processing(reel_db_id: str) -> bool:
    """processing -> new only. Never touches published/failed."""
    return await advance_status(reel_db_id, "processing", "new")


async def mark_reel_published(reel_db_id: str, youtube_video_id: str) -> None:
    client = get_client()
    await client.execute(
        "UPDATE facebook_reels SET status = 'published', youtube_video_id = :youtube_video_id, "
        "youtube_published_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), last_error = NULL, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {"youtube_video_id": youtube_video_id, "id": reel_db_id},
    )


async def mark_reel_scheduled(reel_db_id: str, youtube_video_id: str) -> None:
    """Mark reel as scheduled (uploaded private, waiting for publishAt)."""
    client = get_client()
    await client.execute(
        "UPDATE facebook_reels SET status = 'scheduled', youtube_video_id = :youtube_video_id, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {"youtube_video_id": youtube_video_id, "id": reel_db_id},
    )


async def record_reel_error(reel_db_id: str, error: str) -> None:
    """Persist a failure note + bump retry_count. Never changes status."""
    client = get_client()
    await client.execute(
        "UPDATE facebook_reels SET last_error = :error, retry_count = retry_count + 1, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {"error": (error or "")[:500], "id": reel_db_id},
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
        "ai_processing": by_status.get("ai_processing", 0),
        "queued": by_status.get("queued", 0),
        "processing": by_status.get("processing", 0),
        "published": published,
        "failed": by_status.get("failed", 0),
        "skipped": by_status.get("skipped", 0),
        "unpublished": total - published,
    }


async def pipeline_reel_ai_counts(
    pipeline_id: str, config_hash: str | None = None
) -> dict[str, dict[str, int]]:
    """Inventory and AI metadata counts in one grouped join."""
    client = get_client()
    params: dict[str, Any] = {"pipeline_id": pipeline_id}
    ready_expr = "0"
    if config_hash:
        ready_expr = (
            "SUM(CASE WHEN r.status = 'new' AND m.status = 'generated' "
            "AND m.config_hash = :config_hash THEN 1 ELSE 0 END)"
        )
        params["config_hash"] = config_hash
    rows = await client.execute(
        f"SELECT r.status, m.status, {ready_expr}, COUNT(*) FROM facebook_reels r "
        "LEFT JOIN facebook_ai_metadata m ON m.reel_db_id = r.id "
        f"WHERE {_pipeline_scope(pipeline_id)} "
        "GROUP BY r.status, m.status",
        params,
    )
    inventory_by_status: dict[str, int] = {}
    ai_by_status: dict[str, int] = {}
    total = 0
    ready = 0
    for reel_status, meta_status, ready_count, count in rows.rows or []:
        value = int(count or 0)
        total += value
        ready += int(ready_count or 0)
        inventory_by_status[reel_status] = inventory_by_status.get(reel_status, 0) + value
        if meta_status:
            ai_by_status[meta_status] = ai_by_status.get(meta_status, 0) + value
    published = inventory_by_status.get("published", 0)
    generated = ai_by_status.get("generated", 0)
    failed = ai_by_status.get("failed", 0)
    return {
        "inventory": {
            "total": total,
            "new": inventory_by_status.get("new", 0),
            "ai_processing": inventory_by_status.get("ai_processing", 0),
            "queued": inventory_by_status.get("queued", 0),
            "processing": inventory_by_status.get("processing", 0),
            "published": published,
            "failed": inventory_by_status.get("failed", 0),
            "skipped": inventory_by_status.get("skipped", 0),
            "unpublished": total - published,
        },
        "ai": {
            "generated": generated,
            "failed": failed,
            "pending": max(0, total - generated - failed),
            "total_reels": total,
            "ready": ready,
        },
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


async def recover_orphaned_reel_claims() -> int:
    """Release reels stuck in queued/processing with no live publish-queue job.

    Crash-safe healing, independent of age: a reel claimed by the scheduler
    or publisher whose queue job is gone (terminal, or the worker died
    mid-flight before persisting) would otherwise brick forever — the
    scheduler only picks 'new', the publisher only picks queue rows.
    Reels with a live queued/processing queue job are never touched.

    Orphaned non-terminal publications are failed with a clear code so the
    history is truthful (they read as phantom 'queued' otherwise); the
    scheduler reuses the same row on the next pick via get_or_create dedup
    and overwrites it on success. Returns the number of reels released.
    """
    client = get_client()
    rows = await client.execute(
        """
        SELECT r.id FROM facebook_reels r
        WHERE r.status IN ('queued', 'processing')
        AND NOT EXISTS (
            SELECT 1 FROM facebook_publish_queue q
            WHERE q.reel_db_id = r.id AND q.status IN ('queued', 'processing')
        )
        """
    )
    healed = 0
    for row in rows.rows or []:
        reel_db_id = row[0]
        try:
            await client.execute(
                "UPDATE publications SET status = 'failed', "
                "last_error = 'ORPHANED_JOB_FAILED: queue job gone, reel claim released', "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
                "WHERE reel_db_id = :id AND status NOT IN ('scheduled', 'published', 'failed')",
                {"id": reel_db_id},
            )
        except Exception:
            pass
        released = False
        try:
            if await release_claim(reel_db_id):
                released = True
            if await release_processing(reel_db_id):
                released = True
        except Exception:
            pass
        if released:
            healed += 1
    return healed


async def claim_ai_processing(reel_db_id: str) -> bool:
    """Atomically claim a reel for AI processing: new -> ai_processing.
    
    Returns True only if the reel was in 'new' status.
    """
    client = get_client()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    res = await client.execute(
        "UPDATE facebook_reels SET status = 'ai_processing', ai_claimed_at = :now, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = :id AND status = 'new'",
        {"id": reel_db_id, "now": now_iso},
    )
    return (res.rows_affected or 0) > 0


async def release_ai_claim(reel_db_id: str) -> bool:
    """Release AI claim: ai_processing -> new. Only if currently ai_processing."""
    client = get_client()
    res = await client.execute(
        "UPDATE facebook_reels SET status = 'new', ai_claimed_at = NULL, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = :id AND status = 'ai_processing'",
        {"id": reel_db_id},
    )
    return (res.rows_affected or 0) > 0


async def list_reels_needing_ai(
    pipeline_id: str,
    config_hash: str | None = None,
    limit: int = 100,
    *,
    max_retries: int | None = None,
    now_iso: str | None = None,
) -> list[dict[str, Any]]:
    """Find reels in 'new' status that need AI metadata generation.

    A reel needs AI if:
    - status = 'new'
    - no generated AI metadata with matching config_hash
    - no failed metadata still in backoff or past max retries
    """
    client = get_client()
    source_rows = await client.execute(
        "SELECT id FROM facebook_sources WHERE pipeline_id = :pipeline_id",
        {"pipeline_id": pipeline_id},
    )
    source_ids = [str(r[0]) for r in source_rows.rows or []]
    if not source_ids:
        return []
    placeholders = ",".join(f":src{i}" for i in range(len(source_ids)))
    scope = f"r.source_id IN ({placeholders})"
    params: dict[str, Any] = {
        f"src{i}": source_id for i, source_id in enumerate(source_ids)
    }
    params["limit"] = limit

    if config_hash is None:
        missing_clause = (
            "AND NOT EXISTS ("
            "SELECT 1 FROM facebook_ai_metadata m "
            "WHERE m.reel_db_id = r.id AND m.status = 'generated')"
        )
    else:
        missing_clause = (
            "AND NOT EXISTS ("
            "SELECT 1 FROM facebook_ai_metadata m "
            "WHERE m.reel_db_id = r.id AND m.status = 'generated' "
            "AND m.config_hash = :config_hash)"
        )
        params["config_hash"] = config_hash

    backoff_clause = ""
    if max_retries is not None:
        backoff_clause = (
            "AND NOT EXISTS ("
            "SELECT 1 FROM facebook_ai_metadata mb "
            "WHERE mb.reel_db_id = r.id AND mb.status = 'failed' "
            "AND (mb.retry_count >= :max_retries "
            "OR (mb.next_retry_at IS NOT NULL AND mb.next_retry_at > :now_iso)))"
        )
        params["max_retries"] = max_retries
        params["now_iso"] = now_iso or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    rows = await client.execute(
        f"""
        SELECT {_REEL_COLUMNS} FROM facebook_reels r
        WHERE {scope}
        AND r.status = 'new'
        {missing_clause}
        {backoff_clause}
        ORDER BY r.discovered_at DESC, r.id ASC
        LIMIT :limit
        """,
        params,
    )
    return [_reel_to_dict(r) for r in (rows.rows or [])]


async def list_ai_ready_reels(
    pipeline_id: str,
    config_hash: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Find reels in 'new' status that HAVE generated AI metadata matching config_hash.
    
    These are the reels ready for scheduler to pick up.
    
    A reel is AI-ready if:
    - status = 'new'
    - EXISTS generated AI metadata with matching config_hash
    - pipeline has AI enabled
    """
    client = get_client()
    source_rows = await client.execute(
        "SELECT id FROM facebook_sources WHERE pipeline_id = :pipeline_id",
        {"pipeline_id": pipeline_id},
    )
    source_ids = [str(r[0]) for r in source_rows.rows or []]
    if not source_ids:
        return []
    placeholders = ",".join(f":src{i}" for i in range(len(source_ids)))
    params: dict[str, Any] = {
        f"src{i}": source_id for i, source_id in enumerate(source_ids)
    }
    params["config_hash"] = config_hash
    params["limit"] = limit
    rows = await client.execute(
        f"""
        SELECT {_REEL_COLUMNS} FROM facebook_reels r
        WHERE r.source_id IN ({placeholders})
        AND r.status = 'new'
        AND EXISTS (
            SELECT 1 FROM facebook_ai_metadata m
            WHERE m.reel_db_id = r.id
            AND m.status = 'generated'
            AND m.config_hash = :config_hash
        )
        ORDER BY r.discovered_at DESC, r.id ASC
        LIMIT :limit
        """,
        params,
    )
    return [_reel_to_dict(r) for r in (rows.rows or [])]


async def execute(sql: str, params: dict[str, Any] | None = None) -> Any:
    """Execute raw SQL query."""
    client = get_client()
    return await client.execute(sql, params or {})


async def skip_reel(reel_db_id: str) -> dict[str, Any] | None:
    """Set status to skipped. Returns the updated row or None if not found."""
    client = get_client()
    rows = await client.execute(
        "SELECT id, source_id, reel_id, status FROM facebook_reels WHERE id = :id",
        {"id": reel_db_id},
    )
    if not rows.rows:
        return None
    await client.execute(
        "UPDATE facebook_reels SET status = 'skipped', "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = :id",
        {"id": reel_db_id},
    )
    r = rows.rows[0]
    return {"id": r[0], "source_id": r[1], "reel_id": r[2], "status": "skipped"}


async def restore_reel(reel_db_id: str) -> dict[str, Any] | None:
    """Restore skipped -> new. Returns the updated row or None if not found."""
    client = get_client()
    rows = await client.execute(
        "SELECT id, source_id, reel_id, status FROM facebook_reels WHERE id = :id",
        {"id": reel_db_id},
    )
    if not rows.rows:
        return None
    await client.execute(
        "UPDATE facebook_reels SET status = 'new', "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = :id AND status = 'skipped'",
        {"id": reel_db_id},
    )
    updated = await client.execute(
        "SELECT id, source_id, reel_id, status FROM facebook_reels WHERE id = :id",
        {"id": reel_db_id},
    )
    if not updated.rows or updated.rows[0][3] != "new":
        return None
    r = updated.rows[0]
    return {"id": r[0], "source_id": r[1], "reel_id": r[2], "status": "new"}


async def bulk_skip_reels(pipeline_id: str, reel_db_ids: list[str]) -> dict[str, Any]:
    """Skip reels by DB IDs, validating pipeline ownership.
    
    Returns dict with skipped count, unchanged count, and rejected IDs array.
    Only allows skip from 'new' or 'failed' status.
    """
    client = get_client()
    if not reel_db_ids:
        return {"skipped": 0, "unchanged": 0, "rejected": []}
    
    placeholders = ",".join(f":id{i}" for i in range(len(reel_db_ids)))
    params: dict[str, Any] = {"pipeline_id": pipeline_id}
    for i, rid in enumerate(reel_db_ids):
        params[f"id{i}"] = rid
    
    rows = await client.execute(
        f"SELECT id, status FROM facebook_reels r "
        f"WHERE r.id IN ({placeholders}) AND {_pipeline_scope(pipeline_id)}",
        params,
    )
    found_ids = {r[0]: r[1] for r in rows.rows}
    valid_ids = {rid for rid, status in found_ids.items() if status in ("new", "failed")}
    
    rejected: list[str] = []
    for rid in reel_db_ids:
        if rid not in found_ids:
            rejected.append(rid)
        elif rid not in valid_ids:
            rejected.append(rid)
    
    if not valid_ids:
        return {"skipped": 0, "unchanged": 0, "rejected": rejected}
    
    skip_placeholders = ",".join(f":sid{i}" for i in range(len(valid_ids)))
    skip_params: dict[str, Any] = {}
    for i, vid in enumerate(valid_ids):
        skip_params[f"sid{i}"] = vid
    
    res = await client.execute(
        f"UPDATE facebook_reels SET status = 'skipped', "
        f"updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        f"WHERE id IN ({skip_placeholders}) AND status IN ('new', 'failed')",
        skip_params,
    )
    skipped = res.rows_affected or 0
    unchanged = len(valid_ids) - skipped
    return {
        "skipped": skipped,
        "unchanged": unchanged,
        "rejected": rejected,
    }
