"""Audio pipelines CRUD."""

from __future__ import annotations

from typing import Any

from app.db.client import get_client
from app.db.repositories import new_id, now_iso, slugify


def _row(r: Any) -> dict[str, Any]:
    return {
        "id": r["id"],
        "name": r["name"],
        "slug": r["slug"],
        "enabled": bool(r["enabled"]),
        "auto_publish": bool(r["auto_publish"]),
        "pipeline_type": r["pipeline_type"] if "pipeline_type" in r and r["pipeline_type"] else "auto",
        "created_at": r["created_at"] if "created_at" in r else None,
        "updated_at": r["updated_at"] if "updated_at" in r else None,
    }


def list_pipelines(pipeline_type: str | None = None) -> list[dict[str, Any]]:
    client = get_client()
    if pipeline_type:
        rows = client.execute(
            "SELECT * FROM audio_pipelines WHERE pipeline_type = ? ORDER BY created_at DESC",
            (pipeline_type,),
        ).fetchall()
    else:
        rows = client.execute(
            "SELECT * FROM audio_pipelines ORDER BY created_at DESC"
        ).fetchall()
    return [_row(r) for r in rows]


def get_pipeline(pipeline_id: str) -> dict[str, Any] | None:
    row = get_client().execute(
        "SELECT * FROM audio_pipelines WHERE id = ?", (pipeline_id,)
    ).fetchone()
    return _row(row) if row else None


def create_pipeline(name: str, **fields: Any) -> dict[str, Any]:
    pid = new_id("apl")
    slug = slugify(name)
    pipeline_type = fields.get("pipeline_type", "auto")
    if pipeline_type not in ("auto", "manual"):
        pipeline_type = "auto"
    auto_pub = 0 if pipeline_type == "manual" else (1 if fields.get("auto_publish", True) else 0)
    client = get_client()
    for attempt in range(3):
        try:
            client.execute(
                "INSERT INTO audio_pipelines (id, name, slug, enabled, auto_publish, pipeline_type) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (pid, name.strip(), slug,
                 1 if fields.get("enabled", True) else 0,
                 auto_pub,
                 pipeline_type),
            )
            client.commit()
            break
        except RuntimeError as exc:
            if "UNIQUE" in str(exc) and attempt < 2:
                slug = f"{slug}-{attempt + 2}"
                continue
            raise
    row = get_pipeline(pid)
    assert row is not None
    return row


def update_pipeline(pipeline_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {"name", "enabled", "auto_publish", "pipeline_type"}
    sets, params = [], []
    has_auto_publish = "auto_publish" in fields and fields["auto_publish"] is not None
    for key in allowed:
        if key in fields and fields[key] is not None:
            value = fields[key]
            if key in ("enabled", "auto_publish"):
                value = 1 if value else 0
            elif key == "pipeline_type":
                if value not in ("auto", "manual"):
                    continue
                if value == "manual" and not has_auto_publish:
                    sets.append("auto_publish = ?")
                    params.append(0)
            sets.append(f"{key} = ?")
            params.append(value)
    if not sets:
        return get_pipeline(pipeline_id)
    sets.append("updated_at = ?")
    params.extend([now_iso(), pipeline_id])
    client = get_client()
    client.execute(f"UPDATE audio_pipelines SET {', '.join(sets)} WHERE id = ?", params)
    client.commit()
    return get_pipeline(pipeline_id)


def delete_pipeline(pipeline_id: str) -> bool:
    client = get_client()
    row = client.execute(
        "SELECT COUNT(*) AS n FROM audio_inventory WHERE pipeline_id = ?",
        (pipeline_id,),
    ).fetchone()
    client.execute("DELETE FROM audio_job_events WHERE job_id IN "
                   "(SELECT id FROM audio_processing_jobs WHERE pipeline_id = ?)",
                   (pipeline_id,))
    client.execute("DELETE FROM audio_processing_jobs WHERE pipeline_id = ?",
                   (pipeline_id,))
    client.execute("DELETE FROM audio_publications WHERE pipeline_id = ?", (pipeline_id,))
    client.execute("DELETE FROM audio_inventory WHERE pipeline_id = ?", (pipeline_id,))
    client.execute("DELETE FROM audio_sources WHERE pipeline_id = ?", (pipeline_id,))
    client.execute("DELETE FROM audio_media_assets WHERE pipeline_id = ?", (pipeline_id,))
    client.execute("DELETE FROM audio_destinations WHERE pipeline_id = ?", (pipeline_id,))
    client.execute("DELETE FROM audio_ai_settings WHERE pipeline_id = ?", (pipeline_id,))
    client.execute("DELETE FROM audio_scheduler_settings WHERE pipeline_id = ?",
                   (pipeline_id,))
    client.execute("DELETE FROM audio_pipelines WHERE id = ?", (pipeline_id,))
    client.commit()
    return True


def pipeline_stats(pipeline_id: str) -> dict[str, Any]:
    client = get_client()
    def _count(query: str, *params: Any) -> int:
        r = client.execute(query, params).fetchone()
        try:
            return int(r["n"]) if r and r.get("n") is not None else 0
        except (ValueError, TypeError):
            return 0

    total_sources = _count(
        "SELECT COUNT(*) AS n FROM audio_sources WHERE pipeline_id = ?",
        pipeline_id)
    pending = _count(
        "SELECT COUNT(*) AS n FROM audio_inventory "
        "WHERE pipeline_id = ? AND status = 'available'",
        pipeline_id)
    published = _count(
        "SELECT COUNT(*) AS n FROM audio_publications WHERE pipeline_id = ?",
        pipeline_id)
    running = _count(
        "SELECT COUNT(*) AS n FROM audio_processing_jobs "
        "WHERE pipeline_id = ? AND status IN ('queued','running')",
        pipeline_id)
    failed = _count(
        "SELECT COUNT(*) AS n FROM audio_processing_jobs "
        "WHERE pipeline_id = ? AND status = 'failed'",
        pipeline_id)
    last_pub = client.execute(
        "SELECT youtube_url, published_at FROM audio_publications "
        "WHERE pipeline_id = ? ORDER BY published_at DESC LIMIT 1",
        (pipeline_id,)).fetchone()
    return {
        "total_sources": total_sources,
        "pending_videos": pending,
        "published_videos": published,
        "running_jobs": running,
        "failed_jobs": failed,
        "last_publish": dict(last_pub) if last_pub else None,
    }
