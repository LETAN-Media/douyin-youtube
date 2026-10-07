"""Per-pipeline processing settings + durable series jobs."""

import json
import uuid
from typing import Any

from ..client import get_client

MODES = ("direct_merge", "translate_sub", "dub_vi")


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bool(v: Any) -> bool:
    return bool(v)


def _row_to_settings(r: Any) -> dict[str, Any]:
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
        "pipeline_id": _col("pipeline_id", 0),
        "processing_mode": _col("processing_mode", 1) or "direct_merge",
        "merge_all_episodes": bool(_col("merge_all_episodes", 2, 1)),
        "episodes_per_video": _col("episodes_per_video", 3),
        "target_language": _col("target_language", 4),
        "subtitle_enabled": bool(_col("subtitle_enabled", 5, 1)),
        "tts_enabled": bool(_col("tts_enabled", 6, 0)),
        "template_enabled": bool(_col("template_enabled", 7, 0)),
        "template_id": _col("template_id", 8),
        "template_mode": _col("template_mode", 9),
        "youtube_destination_id": _col("youtube_destination_id", 10),
        "auto_publish": bool(_col("auto_publish", 11, 1)),
    }


def get_settings(pipeline_id: str) -> dict[str, Any]:
    """Defaults when no row exists: direct_merge, merge all, no ASR."""
    conn = get_client()
    try:
        row = conn.execute(
            "SELECT pipeline_id, processing_mode, merge_all_episodes, "
            "episodes_per_video, target_language, subtitle_enabled, tts_enabled, "
            "template_enabled, template_id, template_mode, youtube_destination_id, "
            "auto_publish "
            "FROM drama_pipeline_settings WHERE pipeline_id = ?",
            (pipeline_id,),
        ).fetchone()
    except Exception:
        # Pre-migration DBs without the new columns.
        row = conn.execute(
            "SELECT pipeline_id, processing_mode, merge_all_episodes, "
            "episodes_per_video, target_language, subtitle_enabled, tts_enabled "
            "FROM drama_pipeline_settings WHERE pipeline_id = ?",
            (pipeline_id,),
        ).fetchone()
    if row is None:
        return {
            "pipeline_id": pipeline_id,
            "processing_mode": "direct_merge",
            "merge_all_episodes": True,
            "episodes_per_video": None,
            "target_language": None,
            "subtitle_enabled": True,
            "tts_enabled": False,
            "template_enabled": False,
            "template_id": None,
            "template_mode": None,
            "youtube_destination_id": None,
            "auto_publish": True,
        }
    return _row_to_settings(row)


def update_settings(pipeline_id: str, **fields: Any) -> dict[str, Any]:
    current = get_settings(pipeline_id)
    mode = fields.get("processing_mode", current["processing_mode"])
    if mode not in MODES:
        raise ValueError(f"Invalid processing_mode: {mode!r}. Expected one of {MODES}.")
    merge_all = fields.get("merge_all_episodes", current["merge_all_episodes"])
    epv = fields.get("episodes_per_video", current["episodes_per_video"])
    if not merge_all:
        if epv is None:
            raise ValueError("episodes_per_video is required when merge_all_episodes=false.")
        epv = int(epv)
        if epv < 1 or epv > 200:
            raise ValueError("episodes_per_video must be 1..200.")
    else:
        epv = None
    target_language = fields.get("target_language", current["target_language"])
    if target_language is not None:
        target_language = str(target_language).strip().lower() or None
    template_enabled = bool(fields.get("template_enabled", current["template_enabled"]))
    template_id = fields.get("template_id", current["template_id"])
    if template_id is not None:
        template_id = str(template_id).strip() or None
    template_mode = fields.get("template_mode", current["template_mode"])
    if template_mode is not None:
        template_mode = str(template_mode).strip().lower() or None
        if template_mode not in ("overlay", "frame", "fullscreen"):
            raise ValueError("template_mode must be overlay, frame, or fullscreen.")
    youtube_destination_id = fields.get(
        "youtube_destination_id", current["youtube_destination_id"]
    )
    if youtube_destination_id is not None:
        youtube_destination_id = str(youtube_destination_id).strip() or None
    conn = get_client()
    conn.execute(
        "INSERT INTO drama_pipeline_settings (pipeline_id, processing_mode, "
        "merge_all_episodes, episodes_per_video, target_language, "
        "subtitle_enabled, tts_enabled, template_enabled, template_id, "
        "template_mode, youtube_destination_id, auto_publish, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(pipeline_id) DO UPDATE SET processing_mode = excluded.processing_mode, "
        "merge_all_episodes = excluded.merge_all_episodes, "
        "episodes_per_video = excluded.episodes_per_video, "
        "target_language = excluded.target_language, "
        "subtitle_enabled = excluded.subtitle_enabled, "
        "tts_enabled = excluded.tts_enabled, "
        "template_enabled = excluded.template_enabled, "
        "template_id = excluded.template_id, "
        "template_mode = excluded.template_mode, "
        "youtube_destination_id = excluded.youtube_destination_id, "
        "auto_publish = excluded.auto_publish, "
        "updated_at = excluded.updated_at",
        (
            pipeline_id, mode, 1 if merge_all else 0, epv, target_language,
            1 if fields.get("subtitle_enabled", current["subtitle_enabled"]) else 0,
            1 if fields.get("tts_enabled", current["tts_enabled"]) else 0,
            1 if template_enabled else 0, template_id, template_mode,
            youtube_destination_id,
            1 if fields.get("auto_publish", current["auto_publish"]) else 0,
            _now(),
        ),
    )
    conn.commit()
    return get_settings(pipeline_id)


def plan_chunks(total_episodes: int, settings: dict[str, Any]) -> list[tuple[int, int]]:
    """Split episode numbers (1-based) into chunks.

    merge_all (or no episodes_per_video) -> [(1, total)].
    Otherwise consecutive ranges of episodes_per_video.
    """
    if total_episodes <= 0:
        return []
    if settings.get("merge_all_episodes", True) or not settings.get("episodes_per_video"):
        return [(1, total_episodes)]
    size = int(settings["episodes_per_video"])
    return [
        (start, min(start + size - 1, total_episodes))
        for start in range(1, total_episodes + 1, size)
    ]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _row_to_job(r: Any) -> dict[str, Any]:
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

    try:
        downloaded = json.loads(_col("downloaded_episode_ids_json", 9) or "[]")
        if not isinstance(downloaded, list):
            downloaded = []
    except Exception:
        downloaded = []
    return {
        "id": _col("id", 0),
        "pipeline_id": _col("pipeline_id", 1),
        "series_id": _col("series_id", 2),
        "processing_mode": _col("processing_mode", 3),
        "chunk_index": _col("chunk_index", 4),
        "episode_start": _col("episode_start", 5),
        "episode_end": _col("episode_end", 6),
        "status": _col("status", 7),
        "stage": _col("stage", 8),
        "downloaded_episode_ids": downloaded,
        "output_path": _col("output_path", 10),
        "youtube_video_id": _col("youtube_video_id", 11),
        "last_error_code": _col("last_error_code", 12),
        "last_error_message": _col("last_error_message", 13),
        "upload_progress": _col("upload_progress", 14),
        "template_id": _col("template_id", 15),
    }


def create_job(pipeline_id: str, series_id: str, processing_mode: str,
               chunk_index: int, episode_start: int | None,
               episode_end: int | None) -> dict[str, Any]:
    if processing_mode not in MODES:
        raise ValueError(f"Invalid processing_mode: {processing_mode!r}.")
    conn = get_client()
    jid = _new_id("djob")
    conn.execute(
        "INSERT INTO drama_series_jobs (id, pipeline_id, series_id, processing_mode, "
        "chunk_index, episode_start, episode_end, status, stage, "
        "downloaded_episode_ids_json, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', 'queued', '[]', ?)",
        (jid, pipeline_id, series_id, processing_mode, chunk_index,
         episode_start, episode_end, _now()),
    )
    conn.commit()
    row = get_job(jid)
    assert row is not None
    return row


def get_job(job_id: str) -> dict[str, Any] | None:
    conn = get_client()
    row = conn.execute(
        "SELECT id, pipeline_id, series_id, processing_mode, chunk_index, "
        "episode_start, episode_end, status, stage, downloaded_episode_ids_json, "
        "output_path, youtube_video_id, last_error_code, last_error_message, "
        "upload_progress, template_id "
        "FROM drama_series_jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    return _row_to_job(row) if row is not None else None


def list_jobs(series_id: str) -> list[dict[str, Any]]:
    conn = get_client()
    rows = conn.execute(
        "SELECT id, pipeline_id, series_id, processing_mode, chunk_index, "
        "episode_start, episode_end, status, stage, downloaded_episode_ids_json, "
        "output_path, youtube_video_id, last_error_code, last_error_message, "
        "upload_progress, template_id "
        "FROM drama_series_jobs WHERE series_id = ? ORDER BY chunk_index ASC",
        (series_id,),
    ).fetchall()
    return [_row_to_job(r) for r in rows]


def update_job(job_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {
        "status", "stage", "output_path", "youtube_video_id",
        "last_error_code", "last_error_message",
        "upload_progress", "template_id",
    }
    sets: list[str] = []
    params: list[Any] = []
    for key, value in fields.items():
        if key in allowed:
            sets.append(f"{key} = ?")
            params.append(value)
    if "downloaded_episode_ids" in fields:
        sets.append("downloaded_episode_ids_json = ?")
        params.append(json.dumps(fields["downloaded_episode_ids"]))
    if not sets:
        return get_job(job_id)
    sets.append("updated_at = ?")
    params.append(_now())
    params.append(job_id)
    get_client().execute(
        f"UPDATE drama_series_jobs SET {', '.join(sets)} WHERE id = ?", params
    )
    get_client().commit()
    return get_job(job_id)


def mark_episode_downloaded(job_id: str, episode_db_id: str) -> dict[str, Any] | None:
    job = get_job(job_id)
    if job is None:
        return None
    done = list(job.get("downloaded_episode_ids") or [])
    if episode_db_id not in done:
        done.append(episode_db_id)
    return update_job(job_id, downloaded_episode_ids=done)


def list_pipeline_jobs(pipeline_id: str, limit: int = 50) -> list[dict[str, Any]]:
    conn = get_client()
    rows = conn.execute(
        "SELECT id, pipeline_id, series_id, processing_mode, chunk_index, "
        "episode_start, episode_end, status, stage, downloaded_episode_ids_json, "
        "output_path, youtube_video_id, last_error_code, last_error_message, "
        "upload_progress, template_id "
        "FROM drama_series_jobs WHERE pipeline_id = ? "
        "ORDER BY updated_at DESC, id DESC LIMIT ?",
        (pipeline_id, max(1, min(limit, 200))),
    ).fetchall()
    return [_row_to_job(r) for r in rows]
