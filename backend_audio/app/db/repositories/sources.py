"""Sources + inventory repositories."""

from __future__ import annotations

from typing import Any

from app.db.client import get_client
from app.db.repositories import new_id, now_iso

INVENTORY_STATUSES = ("available", "reserved", "processing", "published",
                      "failed", "skipped")


def add_source(pipeline_id: str, canonical_url: str, username: str,
               page_id: str | None = None) -> tuple[dict[str, Any], bool]:
    client = get_client()
    row = client.execute(
        "SELECT * FROM audio_sources WHERE pipeline_id = ? AND canonical_url = ?",
        (pipeline_id, canonical_url),
    ).fetchone()
    if row:
        return dict(row), False
    sid = new_id("asrc")
    client.execute(
        "INSERT INTO audio_sources (id, pipeline_id, kind, url, canonical_url, "
        "page_id, page_name, enabled) VALUES (?, ?, 'facebook_page', ?, ?, ?, ?, 1)",
        (sid, pipeline_id, canonical_url, canonical_url, page_id, username),
    )
    client.commit()
    row = client.execute("SELECT * FROM audio_sources WHERE id = ?", (sid,)).fetchone()
    return dict(row), True


def list_sources(pipeline_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in get_client().execute(
        "SELECT * FROM audio_sources WHERE pipeline_id = ? ORDER BY created_at",
        (pipeline_id,)).fetchall()]


def set_source_enabled(source_id: str, enabled: bool) -> None:
    client = get_client()
    client.execute("UPDATE audio_sources SET enabled = ?, updated_at = ? WHERE id = ?",
                   (1 if enabled else 0, now_iso(), source_id))
    client.commit()


def delete_source(source_id: str) -> None:
    client = get_client()
    client.execute("DELETE FROM audio_sources WHERE id = ?", (source_id,))
    client.commit()


def touch_source_scanned(source_id: str) -> None:
    client = get_client()
    client.execute(
        "UPDATE audio_sources SET last_scanned_at = ?, updated_at = ? WHERE id = ?",
        (now_iso(), now_iso(), source_id))
    client.commit()


def upsert_inventory_item(pipeline_id: str, source_id: str | None,
                          facebook_video_id: str | None, canonical_url: str,
                          **fields: Any) -> tuple[dict[str, Any], bool]:
    """Dedupe on (pipeline_id, facebook_video_id) when id known,
    else on canonical_url."""
    client = get_client()
    existing = None
    if facebook_video_id:
        existing = client.execute(
            "SELECT * FROM audio_inventory WHERE pipeline_id = ? AND facebook_video_id = ?",
            (pipeline_id, facebook_video_id)).fetchone()
    if existing is None:
        existing = client.execute(
            "SELECT * FROM audio_inventory WHERE pipeline_id = ? AND canonical_url = ?",
            (pipeline_id, canonical_url)).fetchone()
    if existing:
        return dict(existing), False
    iid = new_id("ainv")
    client.execute(
        "INSERT INTO audio_inventory (id, pipeline_id, source_id, facebook_video_id, "
        "canonical_url, thumbnail_url, duration_seconds, caption, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'available')",
        (iid, pipeline_id, source_id, facebook_video_id, canonical_url,
         fields.get("thumbnail_url"), fields.get("duration_seconds"),
         fields.get("caption")))
    client.commit()
    row = client.execute("SELECT * FROM audio_inventory WHERE id = ?", (iid,)).fetchone()
    return dict(row), True


def list_inventory(pipeline_id: str, status: str | None = None,
                   limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
    client = get_client()
    where, params = "pipeline_id = ?", [pipeline_id]
    if status:
        where += " AND status = ?"
        params.append(status)
    r_cnt = client.execute(
        f"SELECT COUNT(*) AS n FROM audio_inventory WHERE {where}", params).fetchone()
    try:
        total = int(r_cnt["n"]) if r_cnt and r_cnt.get("n") is not None else 0
    except (ValueError, TypeError):
        total = 0
    rows = client.execute(
        f"SELECT * FROM audio_inventory WHERE {where} "
        f"ORDER BY discovered_at DESC LIMIT ? OFFSET ?",
        (*params, limit, offset)).fetchall()
    return [dict(r) for r in rows], total


def set_inventory_status(inventory_id: str, status: str) -> None:
    assert status in INVENTORY_STATUSES, status
    client = get_client()
    client.execute("UPDATE audio_inventory SET status = ?, updated_at = ? WHERE id = ?",
                   (status, now_iso(), inventory_id))
    client.commit()


def reserve_next_available(pipeline_id: str, order_mode: str = "oldest_first",
                           source_id: str | None = None) -> dict[str, Any] | None:
    """Atomically claim one available item (single worker => simple UPDATE)."""
    order = "ASC" if order_mode == "oldest_first" else "DESC"
    client = get_client()
    params: list[Any] = [pipeline_id]
    extra = ""
    if source_id:
        extra = " AND source_id = ?"
        params.append(source_id)
    row = client.execute(
        f"SELECT * FROM audio_inventory WHERE pipeline_id = ? AND status = 'available'"
        f"{extra} ORDER BY discovered_at {order} LIMIT 1", params).fetchone()
    if row is None:
        return None
    client.execute(
        "UPDATE audio_inventory SET status = 'reserved', updated_at = ? "
        "WHERE id = ? AND status = 'available'", (now_iso(), row["id"]))
    client.commit()
    fresh = client.execute("SELECT * FROM audio_inventory WHERE id = ?",
                           (row["id"],)).fetchone()
    if fresh and fresh["status"] == "reserved":
        return dict(fresh)
    return None
