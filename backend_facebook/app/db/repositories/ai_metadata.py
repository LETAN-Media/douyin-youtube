"""AI metadata persistence (Task 8A). Original captions are never overwritten."""

import hashlib
import json
from typing import Any

from ..client import get_client


def caption_hash(caption: str | None) -> str:
    return hashlib.sha256((caption or "").strip().encode("utf-8")).hexdigest()


def _row_to_dict(r: Any) -> dict[str, Any]:
    hashtags: list[str] = []
    try:
        parsed = json.loads(r[3]) if r[3] else []
        if isinstance(parsed, list):
            hashtags = [str(h) for h in parsed]
    except Exception:
        hashtags = []
    return {
        "reel_db_id": r[0],
        "title": r[1],
        "description": r[2],
        "hashtags": hashtags,
        "model": r[4],
        "status": r[5],
        "source_caption_hash": r[6],
        "generated_at": r[7],
        "last_error": r[8],
        "retry_count": r[9],
        "created_at": r[10],
        "updated_at": r[11],
    }


async def get_for_reel(reel_db_id: str) -> dict[str, Any] | None:
    client = get_client()
    rows = await client.execute(
        "SELECT reel_db_id, title, description, hashtags_json, model, status, "
        "source_caption_hash, generated_at, last_error, retry_count, created_at, updated_at "
        "FROM facebook_ai_metadata WHERE reel_db_id = :id",
        {"id": reel_db_id},
    )
    if not rows.rows:
        return None
    return _row_to_dict(rows.rows[0])


async def upsert_generated(
    *,
    reel_db_id: str,
    title: str,
    description: str,
    hashtags: list[str],
    model: str,
    source_caption_hash: str,
) -> dict[str, Any]:
    client = get_client()
    await client.execute(
        """
        INSERT INTO facebook_ai_metadata
            (reel_db_id, title, description, hashtags_json, model, status,
             source_caption_hash, generated_at, last_error, retry_count,
             updated_at)
        VALUES (:id, :title, :description, :hashtags, :model, 'generated',
                :hash, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), NULL, 0,
                strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        ON CONFLICT(reel_db_id) DO UPDATE SET
            title = excluded.title,
            description = excluded.description,
            hashtags_json = excluded.hashtags_json,
            model = excluded.model,
            status = 'generated',
            source_caption_hash = excluded.source_caption_hash,
            generated_at = excluded.generated_at,
            last_error = NULL,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        """,
        {
            "id": reel_db_id,
            "title": title,
            "description": description,
            "hashtags": json.dumps(hashtags, ensure_ascii=False),
            "model": model,
            "hash": source_caption_hash,
        },
    )
    row = await get_for_reel(reel_db_id)
    assert row is not None
    return row


async def mark_failed(reel_db_id: str, error: str) -> None:
    client = get_client()
    await client.execute(
        """
        INSERT INTO facebook_ai_metadata (reel_db_id, status, last_error, retry_count)
        VALUES (:id, 'failed', :error, 1)
        ON CONFLICT(reel_db_id) DO UPDATE SET
            status = 'failed',
            last_error = excluded.last_error,
            retry_count = retry_count + 1,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        """,
        {"id": reel_db_id, "error": (error or "")[:500]},
    )


async def needs_generation(reel_db_id: str, caption: str | None, model: str) -> bool:
    """True when no usable cached row exists (missing/failed/stale hash or model)."""
    existing = await get_for_reel(reel_db_id)
    if existing is None:
        return True
    if existing["status"] != "generated":
        return True
    if existing["source_caption_hash"] != caption_hash(caption):
        return True
    if (existing["model"] or "") != (model or ""):
        return True
    return False


async def pipeline_stats(pipeline_id: str) -> dict[str, int]:
    """Counts over reels of a pipeline. Single GROUP BY, no N+1."""
    client = get_client()
    rows = await client.execute(
        "SELECT m.status, COUNT(*) FROM facebook_ai_metadata m "
        "JOIN facebook_reels r ON r.id = m.reel_db_id "
        "WHERE r.source_id IN (SELECT id FROM facebook_sources WHERE pipeline_id = :pipeline_id) "
        "GROUP BY m.status",
        {"pipeline_id": pipeline_id},
    )
    by_status = {r[0]: r[1] for r in (rows.rows or [])}
    total_rows = await client.execute(
        "SELECT COUNT(*) FROM facebook_reels r "
        "WHERE r.source_id IN (SELECT id FROM facebook_sources WHERE pipeline_id = :pipeline_id)",
        {"pipeline_id": pipeline_id},
    )
    total = total_rows.rows[0][0] if total_rows.rows else 0
    generated = by_status.get("generated", 0)
    failed = by_status.get("failed", 0)
    return {
        "generated": generated,
        "failed": failed,
        "pending": max(0, total - generated - failed),
        "total_reels": total,
    }
