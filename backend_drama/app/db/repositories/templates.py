"""Named visual template presets (stored by URL/key, never binary)."""

import uuid
from typing import Any

from ..client import get_client


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_template(r: Any) -> dict[str, Any]:
    get = r.get if hasattr(r, "get") else None

    def _col(name: str, idx: int, default: Any = None):
        if get is not None:
            try:
                v = r[name]
                return v if v is not None else default
            except Exception:
                pass
        try:
            v = r[idx]
            return v if v is not None else default
        except Exception:
            return default

    return {
        "id": _col("id", 0),
        "name": _col("name", 1),
        "asset_url": _col("asset_url", 2),
        "canvas_width": _col("canvas_width", 3, 1280),
        "canvas_height": _col("canvas_height", 4, 720),
        "content_x": _col("content_x", 5, 0),
        "content_y": _col("content_y", 6, 0),
        "content_width": _col("content_width", 7, 1280),
        "content_height": _col("content_height", 8, 720),
    }


def create_template(*, name: str, asset_url: str, canvas_width: int = 1280,
                    canvas_height: int = 720, content_x: int = 0,
                    content_y: int = 0, content_width: int = 1280,
                    content_height: int = 720) -> dict[str, Any]:
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Template name must not be empty.")
    clean_url = (asset_url or "").strip()
    if not clean_url.lower().startswith(("http://", "https://", "file://")):
        raise ValueError("asset_url must be an http(s) or file URL.")
    for label, value in (
        ("canvas_width", canvas_width), ("canvas_height", canvas_height),
        ("content_width", content_width), ("content_height", content_height),
    ):
        if int(value) <= 0:
            raise ValueError(f"{label} must be positive.")
    if int(content_x) < 0 or int(content_y) < 0:
        raise ValueError("content_x/content_y must be >= 0.")
    tid = f"dtpl_{uuid.uuid4().hex[:12]}"
    conn = get_client()
    conn.execute(
        "INSERT INTO drama_templates (id, name, asset_url, canvas_width, "
        "canvas_height, content_x, content_y, content_width, content_height) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (tid, clean_name, clean_url, int(canvas_width), int(canvas_height),
         int(content_x), int(content_y), int(content_width), int(content_height)),
    )
    conn.commit()
    row = get_template(tid)
    assert row is not None
    return row


def get_template(template_id: str) -> dict[str, Any] | None:
    conn = get_client()
    row = conn.execute(
        "SELECT id, name, asset_url, canvas_width, canvas_height, content_x, "
        "content_y, content_width, content_height "
        "FROM drama_templates WHERE id = ?",
        (template_id,),
    ).fetchone()
    return _row_to_template(row) if row is not None else None


def list_templates() -> list[dict[str, Any]]:
    conn = get_client()
    rows = conn.execute(
        "SELECT id, name, asset_url, canvas_width, canvas_height, content_x, "
        "content_y, content_width, content_height "
        "FROM drama_templates ORDER BY created_at ASC, id ASC"
    ).fetchall()
    return [_row_to_template(r) for r in rows]


def delete_template(template_id: str) -> bool:
    conn = get_client()
    if get_template(template_id) is None:
        return False
    conn.execute("DELETE FROM drama_templates WHERE id = ?", (template_id,))
    conn.commit()
    return True
