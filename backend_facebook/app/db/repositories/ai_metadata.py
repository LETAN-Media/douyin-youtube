"""AI metadata persistence (Task 8A). Original captions are never overwritten."""

import hashlib
import json
from typing import Any

from ..client import get_client


def source_hash(caption: str | None, reel_id: str | None) -> str:
    material = (caption or "").strip() + "\n" + (reel_id or "").strip()
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def caption_hash(caption: str | None, reel_id: str | None = None) -> str:
    """Legacy alias kept for compatibility; hashes caption + reel_id."""
    return source_hash(caption, reel_id)


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
        "source_hash": r[6],
        "generated_at": r[7],
        "last_error": r[8],
        "retry_count": r[9],
        "created_at": r[10],
        "updated_at": r[11],
        "config_hash": r[12] if len(r) > 12 else None,
        "next_retry_at": r[13] if len(r) > 13 else None,
    }


async def get_for_reel(reel_db_id: str) -> dict[str, Any] | None:
    client = get_client()
    rows = await client.execute(
        "SELECT reel_db_id, title, description, hashtags_json, model, status, "
        "source_hash, generated_at, last_error, retry_count, created_at, updated_at, config_hash, next_retry_at "
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
    source_hash: str,
    config_hash: str | None = None,
) -> dict[str, Any]:
    client = get_client()
    if config_hash is None:
        from .ai_settings import (
            DEFAULT_DESCRIPTION_TEMPLATE,
            DEFAULT_ENABLED,
            DEFAULT_LANGUAGE,
            DEFAULT_LOCKED_HASHTAGS,
            DEFAULT_SYSTEM_PROMPT,
            DEFAULT_TITLE_TEMPLATE,
            compute_config_hash,
        )
        config_hash = compute_config_hash(
            enabled=DEFAULT_ENABLED,
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            title_template=DEFAULT_TITLE_TEMPLATE,
            description_template=DEFAULT_DESCRIPTION_TEMPLATE,
            locked_hashtags=DEFAULT_LOCKED_HASHTAGS,
            language=DEFAULT_LANGUAGE,
            model=model,
        )
    await client.execute(
        """
        INSERT INTO facebook_ai_metadata
            (reel_db_id, title, description, hashtags_json, model, status,
             source_hash, config_hash, generated_at, last_error, retry_count,
             updated_at)
        VALUES (:id, :title, :description, :hashtags, :model, 'generated',
                :hash, :config_hash, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), NULL, 0,
                strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        ON CONFLICT(reel_db_id) DO UPDATE SET
            title = excluded.title,
            description = excluded.description,
            hashtags_json = excluded.hashtags_json,
            model = excluded.model,
            status = 'generated',
            source_hash = excluded.source_hash,
            config_hash = excluded.config_hash,
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
            "hash": source_hash,
            "config_hash": config_hash,
        },
    )
    row = await get_for_reel(reel_db_id)
    assert row is not None
    return row


async def mark_failed(
    reel_db_id: str,
    error: str,
    retry_count: int | None = None,
    next_retry_at: str | None = None,
) -> None:
    client = get_client()
    if retry_count is None:
        # Increment existing retry count
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
    else:
        await client.execute(
            """
            INSERT INTO facebook_ai_metadata (reel_db_id, status, last_error, retry_count, next_retry_at)
            VALUES (:id, 'failed', :error, :retry_count, :next_retry_at)
            ON CONFLICT(reel_db_id) DO UPDATE SET
                status = 'failed',
                last_error = excluded.last_error,
                retry_count = excluded.retry_count,
                next_retry_at = excluded.next_retry_at,
                updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            """,
            {"id": reel_db_id, "error": (error or "")[:500], "retry_count": retry_count, "next_retry_at": next_retry_at},
        )


async def needs_generation(
    reel_db_id: str,
    caption: str | None,
    model: str,
    reel_id: str | None = None,
    config_hash: str | None = None,
) -> bool:
    """True when no usable cached row exists (missing/failed/stale hash, model, or config)."""
    existing = await get_for_reel(reel_db_id)
    if existing is None:
        return True
    if existing["status"] != "generated":
        return True
    if existing["source_hash"] != source_hash(caption, reel_id):
        return True
    if (existing["model"] or "") != (model or ""):
        return True
    if config_hash is not None:
        existing_hash = existing.get("config_hash")
        if existing_hash is None:
            from .ai_settings import (
                DEFAULT_DESCRIPTION_TEMPLATE,
                DEFAULT_ENABLED,
                DEFAULT_LANGUAGE,
                DEFAULT_LOCKED_HASHTAGS,
                DEFAULT_SYSTEM_PROMPT,
                DEFAULT_TITLE_TEMPLATE,
                compute_config_hash,
            )
            default_hash = compute_config_hash(
                enabled=DEFAULT_ENABLED,
                system_prompt=DEFAULT_SYSTEM_PROMPT,
                title_template=DEFAULT_TITLE_TEMPLATE,
                description_template=DEFAULT_DESCRIPTION_TEMPLATE,
                locked_hashtags=DEFAULT_LOCKED_HASHTAGS,
                language=DEFAULT_LANGUAGE,
                model=model,
            )
            if config_hash != default_hash:
                return True
        elif existing_hash != config_hash:
            return True
    return False


async def get_sample_for_pipeline(pipeline_id: str) -> dict[str, Any] | None:
    """Fetch the latest generated metadata row for a pipeline."""
    client = get_client()
    rows = await client.execute(
        """
        SELECT m.reel_db_id, m.title, m.description, m.hashtags_json, m.model,
               m.status, m.source_hash, m.generated_at, m.last_error, m.retry_count,
               m.created_at, m.updated_at, m.config_hash
        FROM facebook_ai_metadata m
        JOIN facebook_reels r ON r.id = m.reel_db_id
        JOIN facebook_sources s ON s.id = r.source_id
        WHERE s.pipeline_id = :pipeline_id AND m.status = 'generated'
        ORDER BY m.generated_at DESC, m.updated_at DESC
        LIMIT 1
        """,
        {"pipeline_id": pipeline_id},
    )
    if not rows.rows:
        return None
    return _row_to_dict(rows.rows[0])


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


async def get_global_stats() -> dict[str, int]:
    """Global counts over all metadata rows. Single GROUP BY, no N+1."""
    client = get_client()
    rows = await client.execute(
        "SELECT m.status, COUNT(*) FROM facebook_ai_metadata m GROUP BY m.status",
    )
    by_status = {r[0]: r[1] for r in (rows.rows or [])}
    generated = by_status.get("generated", 0)
    failed = by_status.get("failed", 0)
    return {
        "generated": generated,
        "failed": failed,
        "total_rows": sum(by_status.values()),
    }
