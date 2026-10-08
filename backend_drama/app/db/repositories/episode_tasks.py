"""Per-episode task state for series jobs (resume + per-episode retry).

One row per (job_id, episode_id). Statuses: pending, downloading,
rendering, rendered, failed. A rendered task is never repeated unless
explicitly reset — this is what makes resume and single-episode retry
safe.
"""

from typing import Any

from ..client import get_client


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_task(r: Any) -> dict[str, Any]:
    get = r.get if hasattr(r, "get") else None

    def _col(name: str, idx: int):
        if get is not None:
            try:
                return r[name]
            except Exception:
                pass
        try:
            return r[idx]
        except Exception:
            return None

    return {
        "id": _col("id", 0),
        "job_id": _col("job_id", 1),
        "episode_id": _col("episode_id", 2),
        "episode_number": _col("episode_number", 3),
        "status": _col("status", 4),
        "render_progress": _col("render_progress", 5),
        "segment_path": _col("segment_path", 6),
        "segment_bytes": _col("segment_bytes", 7),
        "duration": _col("duration", 8),
        "attempt_count": _col("attempt_count", 9),
        "last_error_code": _col("last_error_code", 10),
        "last_error_message": _col("last_error_message", 11),
        "started_at": _col("started_at", 12),
        "completed_at": _col("completed_at", 13),
    }


_COLUMNS = (
    "id, job_id, episode_id, episode_number, status, render_progress, "
    "segment_path, segment_bytes, duration, attempt_count, "
    "last_error_code, last_error_message, started_at, completed_at"
)


def ensure_tasks(job_id: str, episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create pending rows for episodes missing them. Idempotent."""
    import uuid

    conn = get_client()
    for ep in episodes:
        conn.execute(
            "INSERT INTO drama_episode_tasks (id, job_id, episode_id, "
            "episode_number, status, updated_at) VALUES (?, ?, ?, ?, 'pending', ?) "
            "ON CONFLICT(job_id, episode_id) DO NOTHING",
            (f"etask_{uuid.uuid4().hex[:12]}", job_id, ep["id"],
             ep["episode_number"], _now()),
        )
    conn.commit()
    return list_tasks(job_id)


def get_task(job_id: str, episode_db_id: str) -> dict[str, Any] | None:
    conn = get_client()
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM drama_episode_tasks "
        "WHERE job_id = ? AND episode_id = ?",
        (job_id, episode_db_id),
    ).fetchone()
    return _row_to_task(row) if row is not None else None


def list_tasks(job_id: str) -> list[dict[str, Any]]:
    conn = get_client()
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM drama_episode_tasks WHERE job_id = ? "
        "ORDER BY episode_number ASC, episode_id ASC",
        (job_id,),
    ).fetchall()
    return [_row_to_task(r) for r in rows]


def mark_status(job_id: str, episode_db_id: str, status: str, **fields: Any) -> None:
    allowed = {
        "render_progress", "segment_path", "segment_bytes", "duration",
        "last_error_code", "last_error_message", "started_at", "completed_at",
    }
    sets = ["status = ?", "updated_at = ?"]
    params: list[Any] = [status, _now()]
    for key, value in fields.items():
        if key in allowed:
            sets.append(f"{key} = ?")
            params.append(value)
    if status in ("downloading", "rendering") and "started_at" not in fields:
        sets.append("started_at = COALESCE(started_at, ?)")
        params.append(_now())
    if status in ("rendered", "failed"):
        sets.append("completed_at = ?")
        params.append(_now())
    params.extend([job_id, episode_db_id])
    conn = get_client()
    conn.execute(
        f"UPDATE drama_episode_tasks SET {', '.join(sets)} "
        "WHERE job_id = ? AND episode_id = ?",
        params,
    )
    if status in ("downloading", "rendering"):
        conn.execute(
            "UPDATE drama_episode_tasks SET attempt_count = attempt_count + 1 "
            "WHERE job_id = ? AND episode_id = ?",
            (job_id, episode_db_id),
        )
    conn.commit()


def reset_tasks(job_id: str, episode_db_ids: list[str] | None = None,
                only_failed: bool = False) -> int:
    """Reset tasks to pending for retry. Returns rows reset."""
    conn = get_client()
    where = "job_id = ?"
    params: list[Any] = [job_id]
    if episode_db_ids:
        placeholders = ",".join("?" for _ in episode_db_ids)
        where += f" AND episode_id IN ({placeholders})"
        params.extend(episode_db_ids)
    if only_failed:
        where += " AND status = 'failed'"
    conn = get_client()
    before = conn.execute(
        f"SELECT COUNT(*) FROM drama_episode_tasks WHERE {where}", params
    ).fetchone()
    conn.execute(
        "UPDATE drama_episode_tasks SET status = 'pending', "
        "last_error_code = NULL, last_error_message = NULL, "
        "completed_at = NULL, updated_at = ? "
        f"WHERE {where}",
        [_now(), *params],
    )
    conn.commit()
    try:
        return int(before[0]) if before else 0
    except Exception:
        return 0


def count_by_status(job_id: str) -> dict[str, int]:
    conn = get_client()
    rows = conn.execute(
        "SELECT status, COUNT(*) FROM drama_episode_tasks WHERE job_id = ? "
        "GROUP BY status",
        (job_id,),
    ).fetchall()
    out: dict[str, int] = {}
    for r in rows:
        try:
            out[str(r[0])] = int(r[1])
        except Exception:
            continue
    return out
