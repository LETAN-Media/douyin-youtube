"""Destinations, media assets, AI settings, scheduler settings repos."""

from __future__ import annotations

import json
from typing import Any

from app.db.client import get_client
from app.db.repositories import new_id, now_iso


# ---- destinations ----

def create_destination(pipeline_id: str) -> dict[str, Any]:
    did = new_id("aud")
    client = get_client()
    client.execute(
        "INSERT INTO audio_destinations (id, pipeline_id, connected) "
        "VALUES (?, ?, 0)", (did, pipeline_id))
    client.commit()
    return get_destination(did)


def get_destination(destination_id: str) -> dict[str, Any] | None:
    row = get_client().execute(
        "SELECT * FROM audio_destinations WHERE id = ?", (destination_id,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["enabled"] = bool(out.get("enabled", 1))
    out["connected"] = bool(out.get("connected", 0))
    return out


def list_destinations(pipeline_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in get_client().execute(
        "SELECT * FROM audio_destinations WHERE pipeline_id = ? ORDER BY created_at",
        (pipeline_id,)).fetchall()]


def update_destination(destination_id: str, **fields: Any) -> dict | None:
    allowed = {"channel_id", "channel_title", "channel_thumbnail", "visibility",
               "enabled"}
    sets, params = [], []
    for key in allowed:
        if key in fields and fields[key] is not None:
            sets.append(f"{key} = ?")
            params.append(fields[key])
    if sets:
        sets.append("updated_at = ?")
        params.extend([now_iso(), destination_id])
        client = get_client()
        client.execute(
            f"UPDATE audio_destinations SET {', '.join(sets)} WHERE id = ?",
            params)
        client.commit()
    return get_destination(destination_id)


def delete_destination(destination_id: str) -> None:
    client = get_client()
    client.execute("DELETE FROM audio_youtube_credentials WHERE destination_id = ?",
                   (destination_id,))
    client.execute("DELETE FROM audio_destinations WHERE id = ?", (destination_id,))
    client.commit()


def resolve_destination_for_job(pipeline_id: str,
                                job: dict[str, Any]) -> dict[str, Any] | None:
    """Scheduler-chosen destination wins; else the pipeline's connected one."""
    from app.db.repositories import scheduler as sched_repo

    sched = sched_repo.get_settings(pipeline_id)
    candidates: list[dict[str, Any]] = []
    if sched.get("destination_id"):
        dest = get_destination(sched["destination_id"])
        if dest and dest.get("connected") and dest.get("enabled"):
            return dest
    for dest in list_destinations(pipeline_id):
        if dest.get("connected") and dest.get("enabled"):
            candidates.append(dest)
    return candidates[0] if candidates else None


# ---- media assets ----

def add_asset(pipeline_id: str, kind: str, object_key: str, **fields: Any) -> dict:
    aid = new_id("amedia")
    client = get_client()
    client.execute(
        "INSERT INTO audio_media_assets (id, pipeline_id, kind, object_key, file_name, "
        "mime, width, height, duration_seconds, bytes, enabled) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1) "
        "ON CONFLICT(pipeline_id, object_key) DO UPDATE SET enabled=1, "
        "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now')",
        (aid, pipeline_id, kind, object_key, fields.get("file_name"),
         fields.get("mime"), fields.get("width"), fields.get("height"),
         fields.get("duration_seconds"), fields.get("bytes")))
    client.commit()
    row = client.execute(
        "SELECT * FROM audio_media_assets WHERE pipeline_id = ? AND object_key = ?",
        (pipeline_id, object_key)).fetchone()
    return dict(row)


def list_assets(pipeline_id: str, kind: str | None = None) -> list[dict[str, Any]]:
    client = get_client()
    if kind:
        rows = client.execute(
            "SELECT * FROM audio_media_assets WHERE pipeline_id = ? AND kind = ? "
            "ORDER BY created_at", (pipeline_id, kind)).fetchall()
    else:
        rows = client.execute(
            "SELECT * FROM audio_media_assets WHERE pipeline_id = ? ORDER BY created_at",
            (pipeline_id,)).fetchall()
    return [dict(r) for r in rows]


def set_asset_enabled(asset_id: str, enabled: bool) -> None:
    client = get_client()
    client.execute("UPDATE audio_media_assets SET enabled = ?, updated_at = ? WHERE id = ?",
                   (1 if enabled else 0, now_iso(), asset_id))
    client.commit()


def delete_asset(asset_id: str) -> dict | None:
    row = get_client().execute(
        "SELECT * FROM audio_media_assets WHERE id = ?", (asset_id,)).fetchone()
    if row:
        get_client().execute("DELETE FROM audio_media_assets WHERE id = ?",
                             (asset_id,))
        get_client().commit()
        return dict(row)
    return None


def pick_random_background(pipeline_id: str,
                           avoid_asset_id: str | None = None) -> dict | None:
    """Random enabled background, avoiding immediate repeat when possible."""
    import random

    assets = [a for a in list_assets(pipeline_id, "background") if a.get("enabled")]
    if not assets:
        return None
    pool = [a for a in assets if a["id"] != avoid_asset_id] or assets
    return random.choice(pool)


def pick_random_template(pipeline_id: str) -> dict | None:
    """Random enabled template (auto mode). ~10 per pipeline, one per job."""
    import random

    assets = [a for a in list_assets(pipeline_id, "template") if a.get("enabled")]
    if not assets:
        return None
    return random.choice(assets)


# ---- AI settings ----

AI_DEFAULTS = {
    "enabled": False, "language": "vi", "genre": None,
    "generate_title": True, "generate_description": True,
    "generate_hashtags": True, "system_prompt": None,
    "title_template": None, "description_template": None,
    "locked_hashtags": [], "model_override": None, "config_version": 1,
}


class VersionConflict(Exception):
    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(f"expected v{expected}, current v{actual}")
        self.expected, self.actual = expected, actual


def _parse_locked(raw: Any) -> list[str]:
    try:
        items = json.loads(raw or "[]")
        return [str(x) for x in items if str(x).strip()]
    except Exception:
        if isinstance(raw, str) and raw.strip() and not raw.strip().startswith("["):
            return [p.strip() for p in raw.replace("\n", ",").split(",") if p.strip()]
        return []


def get_ai_settings(pipeline_id: str) -> dict[str, Any]:
    row = get_client().execute(
        "SELECT * FROM audio_ai_settings WHERE pipeline_id = ?",
        (pipeline_id,)).fetchone()
    if row is None:
        return {"pipeline_id": pipeline_id, **AI_DEFAULTS,
                "created_at": None, "updated_at": None}
    out = dict(row)
    out["enabled"] = bool(out.get("enabled"))
    for flag in ("generate_title", "generate_description", "generate_hashtags"):
        out[flag] = bool(out.get(flag, 1))
    out["locked_hashtags"] = _parse_locked(out.get("locked_hashtags_json"))
    out["genre"] = _parse_genre(out.get("genre"))
    out["config_version"] = int(out.get("config_version") or 1)
    return out


def _parse_genre(raw: Any) -> list[str] | None:
    """Genre is multi-select: stored as JSON array; legacy plain strings kept."""
    if raw is None:
        return None
    if isinstance(raw, list):
        items = [str(x).strip() for x in raw if str(x).strip()]
        return items or None
    text = str(raw).strip()
    if not text:
        return None
    if text.startswith("["):
        try:
            items = json.loads(text)
            if isinstance(items, list):
                items = [str(x).strip() for x in items if str(x).strip()]
                return items or None
        except Exception:
            pass
    return [text]


def upsert_ai_settings(pipeline_id: str, **fields: Any) -> dict[str, Any]:
    current = get_ai_settings(pipeline_id)
    expected = fields.pop("expected_config_version", None)
    if expected is not None and int(expected) != int(current.get("config_version") or 1):
        raise VersionConflict(int(expected), int(current.get("config_version") or 1))

    def pick(key: str, default: Any, is_bool: bool = False):
        if key not in fields:
            return current.get(key, default)
        value = fields[key]
        if is_bool:
            return bool(value)
        if key == "locked_hashtags":
            return value if isinstance(value, list) else _parse_locked(value)
        if key == "genre":
            if value is None:
                return None
            if isinstance(value, list):
                items = [str(x).strip() for x in value if str(x).strip()]
                return json.dumps(items, ensure_ascii=False) if items else None
            text = str(value).strip()
            if text.startswith("["):
                try:
                    items = json.loads(text)
                    if isinstance(items, list):
                        return json.dumps(
                            [str(x).strip() for x in items if str(x).strip()],
                            ensure_ascii=False)
                except Exception:
                    pass
            return text or None
        if isinstance(value, str):
            return value.strip() or None
        return value

    language = str(fields.get("language", current.get("language") or "vi")).lower()
    if language not in ("vi", "en", "zh"):
        language = "vi"
    new_version = int(current.get("config_version") or 1) + 1
    locked = pick("locked_hashtags", [])
    client = get_client()
    client.execute(
        "INSERT INTO audio_ai_settings (pipeline_id, enabled, language, genre, "
        "generate_title, generate_description, generate_hashtags, system_prompt, "
        "title_template, description_template, locked_hashtags_json, model_override, "
        "config_version, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(pipeline_id) DO UPDATE SET enabled=excluded.enabled, "
        "language=excluded.language, genre=excluded.genre, "
        "generate_title=excluded.generate_title, "
        "generate_description=excluded.generate_description, "
        "generate_hashtags=excluded.generate_hashtags, "
        "system_prompt=excluded.system_prompt, title_template=excluded.title_template, "
        "description_template=excluded.description_template, "
        "locked_hashtags_json=excluded.locked_hashtags_json, "
        "model_override=excluded.model_override, "
        "config_version=excluded.config_version, "
        "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now')",
        (pipeline_id, 1 if pick("enabled", False, True) else 0, language,
         pick("genre", None),
         1 if pick("generate_title", True, True) else 0,
         1 if pick("generate_description", True, True) else 0,
         1 if pick("generate_hashtags", True, True) else 0,
         pick("system_prompt", None), pick("title_template", None),
         pick("description_template", None), json.dumps(locked, ensure_ascii=False),
         pick("model_override", None), new_version, now_iso()))
    client.commit()
    return get_ai_settings(pipeline_id)


def reset_ai_settings(pipeline_id: str) -> dict[str, Any]:
    current = get_ai_settings(pipeline_id)
    client = get_client()
    client.execute(
        "INSERT INTO audio_ai_settings (pipeline_id, enabled, language, "
        "generate_title, generate_description, generate_hashtags, "
        "locked_hashtags_json, config_version, updated_at) "
        "VALUES (?, 0, 'vi', 1, 1, 1, '[]', ?, ?) "
        "ON CONFLICT(pipeline_id) DO UPDATE SET enabled=0, language='vi', "
        "genre=NULL, generate_title=1, generate_description=1, generate_hashtags=1, "
        "system_prompt=NULL, title_template=NULL, description_template=NULL, "
        "locked_hashtags_json='[]', model_override=NULL, "
        "config_version=excluded.config_version, "
        "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now')",
        (pipeline_id, int(current.get("config_version") or 1) + 1, now_iso()))
    client.commit()
    return get_ai_settings(pipeline_id)


# ---- scheduler settings ----

def get_scheduler_settings(pipeline_id: str) -> dict[str, Any]:
    row = get_client().execute(
        "SELECT * FROM audio_scheduler_settings WHERE pipeline_id = ?",
        (pipeline_id,)).fetchone()
    if row is None:
        return {"pipeline_id": pipeline_id, "enabled": False,
                "destination_id": None, "max_videos_per_day": 3,
                "min_gap_minutes": 120, "timezone": "Asia/Ho_Chi_Minh",
                "daily_times": [], "order_mode": "oldest_first",
                "rotate_sources": True, "next_run_at": None, "last_run_at": None}
    out = dict(row)
    out["enabled"] = bool(out.get("enabled"))
    out["rotate_sources"] = bool(out.get("rotate_sources", 1))
    try:
        out["daily_times"] = json.loads(out.get("daily_times_json") or "[]")
    except Exception:
        out["daily_times"] = []
    return out


def upsert_scheduler_settings(pipeline_id: str, **fields: Any) -> dict[str, Any]:
    current = get_scheduler_settings(pipeline_id)

    def pick(key: str, default: Any):
        return fields[key] if key in fields else current.get(key, default)

    times = pick("daily_times", [])
    if isinstance(times, str):
        try:
            times = json.loads(times)
        except Exception:
            times = []
    order = pick("order_mode", "oldest_first")
    if order not in ("oldest_first", "newest_first"):
        order = "oldest_first"
    client = get_client()
    client.execute(
        "INSERT INTO audio_scheduler_settings (pipeline_id, enabled, destination_id, "
        "max_videos_per_day, min_gap_minutes, timezone, daily_times_json, order_mode, "
        "rotate_sources, next_run_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(pipeline_id) DO UPDATE SET enabled=excluded.enabled, "
        "destination_id=excluded.destination_id, "
        "max_videos_per_day=excluded.max_videos_per_day, "
        "min_gap_minutes=excluded.min_gap_minutes, timezone=excluded.timezone, "
        "daily_times_json=excluded.daily_times_json, "
        "order_mode=excluded.order_mode, rotate_sources=excluded.rotate_sources, "
        "next_run_at=excluded.next_run_at, "
        "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now')",
        (pipeline_id, 1 if pick("enabled", False) else 0,
         pick("destination_id", None),
         max(1, min(20, int(pick("max_videos_per_day", 3) or 3))),
         max(15, int(pick("min_gap_minutes", 120) or 120)),
         str(pick("timezone", "Asia/Ho_Chi_Minh") or "Asia/Ho_Chi_Minh")[:64],
         json.dumps(times if isinstance(times, list) else []),
         order, 1 if pick("rotate_sources", True) else 0,
         pick("next_run_at", current.get("next_run_at")), now_iso()))
    client.commit()
    return get_scheduler_settings(pipeline_id)


def set_scheduler_run_marks(pipeline_id: str, *, last_run_at: str | None = None,
                            next_run_at: str | None = None) -> None:
    client = get_client()
    if last_run_at is not None:
        client.execute("UPDATE audio_scheduler_settings SET last_run_at = ? "
                       "WHERE pipeline_id = ?", (last_run_at, pipeline_id))
    if next_run_at is not None:
        client.execute("UPDATE audio_scheduler_settings SET next_run_at = ? "
                       "WHERE pipeline_id = ?", (next_run_at, pipeline_id))
    client.commit()
