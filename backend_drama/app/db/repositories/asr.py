"""JianYing ASR result persistence (drama_episode_asr).

Only SRT text + metadata are stored. Never source videos, signed URLs,
or local /tmp paths.
"""

from typing import Any

from ..client import get_client


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_asr(r: Any) -> dict[str, Any]:
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
        "episode_id": _col("episode_id", 0),
        "series_id": _col("series_id", 1),
        "status": _col("status", 2),
        "source_language": _col("source_language", 3),
        "engine": _col("engine", 4),
        "srt_text": _col("srt_text", 5),
        "segment_count": _col("segment_count", 6),
        "duration_ms": _col("duration_ms", 7),
        "attempt_count": _col("attempt_count", 8),
        "last_error_code": _col("last_error_code", 9),
        "last_error_message": _col("last_error_message", 10),
        "started_at": _col("started_at", 11),
        "completed_at": _col("completed_at", 12),
        "updated_at": _col("updated_at", 13),
    }


def start_asr(episode_id: str, series_id: str) -> dict[str, Any]:
    """Mark running (upsert). Bumps attempt_count."""
    conn = get_client()
    conn.execute(
        "INSERT INTO drama_episode_asr (episode_id, series_id, status, started_at, "
        "attempt_count, updated_at) VALUES (?, ?, 'processing', ?, 1, ?) "
        "ON CONFLICT(episode_id) DO UPDATE SET status = 'processing', "
        "started_at = ?, attempt_count = attempt_count + 1, "
        "last_error_code = NULL, last_error_message = NULL, updated_at = ?",
        (episode_id, series_id, _now(), _now(), _now(), _now()),
    )
    conn.commit()
    row = get_asr(episode_id)
    assert row is not None
    return row


def complete_asr(episode_id: str, *, source_language: str | None,
                 srt_text: str, segment_count: int,
                 duration_ms: int | None) -> dict[str, Any]:
    conn = get_client()
    conn.execute(
        "UPDATE drama_episode_asr SET status = 'completed', source_language = ?, "
        "engine = 'jianying', srt_text = ?, segment_count = ?, duration_ms = ?, "
        "completed_at = ?, updated_at = ? WHERE episode_id = ?",
        (source_language, srt_text, segment_count, duration_ms,
         _now(), _now(), episode_id),
    )
    conn.commit()
    row = get_asr(episode_id)
    assert row is not None
    return row


def fail_asr(episode_id: str, series_id: str, *, code: str,
             message: str) -> dict[str, Any]:
    conn = get_client()
    conn.execute(
        "INSERT INTO drama_episode_asr (episode_id, series_id, status, "
        "last_error_code, last_error_message, updated_at) "
        "VALUES (?, ?, 'failed', ?, ?, ?) "
        "ON CONFLICT(episode_id) DO UPDATE SET status = 'failed', "
        "attempt_count = attempt_count + 1, last_error_code = excluded.last_error_code, "
        "last_error_message = excluded.last_error_message, updated_at = excluded.updated_at",
        (episode_id, series_id, code[:64], (message or "")[:2000], _now()),
    )
    conn.commit()
    row = get_asr(episode_id)
    assert row is not None
    return row


def get_asr(episode_id: str) -> dict[str, Any] | None:
    conn = get_client()
    row = conn.execute(
        "SELECT episode_id, series_id, status, source_language, engine, srt_text, "
        "segment_count, duration_ms, attempt_count, last_error_code, "
        "last_error_message, started_at, completed_at, updated_at "
        "FROM drama_episode_asr WHERE episode_id = ?",
        (episode_id,),
    ).fetchone()
    return _row_to_asr(row) if row is not None else None
