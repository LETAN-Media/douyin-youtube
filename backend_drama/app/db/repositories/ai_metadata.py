"""Per-pipeline AI YouTube metadata settings + generation cache (Turso)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..client import get_client

LANGUAGES = ("vi", "en", "zh")


def normalize_language(value: Any) -> str:
    lang = str(value or "").strip().lower()
    if lang in ("vn", "vietnamese", "tiếng việt"):
        return "vi"
    if lang in ("english",):
        return "en"
    if lang in ("chinese", "simplified", "中文"):
        return "zh"
    return lang if lang in LANGUAGES else "vi"


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _parse_tags(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str):
        try:
            items = json.loads(raw) if raw.strip().startswith("[") else re_split(raw)
        except Exception:
            items = re_split(raw)
    else:
        return []
    out: list[str] = []
    for item in items:
        tag = str(item or "").strip()
        if tag and tag not in out:
            out.append(tag)
    return out


def re_split(raw: str) -> list[str]:
    import re as _re

    return [p for p in _re.split(r"[,\n]+", raw or "") if p.strip()]


def default_settings(pipeline_id: str) -> dict[str, Any]:
    return {
        "pipeline_id": pipeline_id,
        "enabled": False,
        "language": "vi",
        "generate_title": True,
        "generate_description": True,
        "generate_hashtags": True,
        "system_prompt": None,
        "title_template": None,
        "description_template": None,
        "locked_hashtags": [],
        "model_override": None,
        "config_version": 1,
        "created_at": None,
        "updated_at": None,
    }


class VersionConflict(Exception):
    """Raised when expected_config_version does not match the stored version."""

    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(
            f"Settings changed by another session "
            f"(expected v{expected}, current v{actual}). Reload and retry."
        )
        self.expected = expected
        self.actual = actual


def _row_to_settings(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    get = row.get if hasattr(row, "get") else None

    def col(name: str, idx: int):
        if get is not None:
            try:
                return row[name]
            except Exception:
                pass
        try:
            return row[idx]
        except Exception:
            return None

    return {
        "pipeline_id": col("pipeline_id", 0),
        "enabled": bool(col("enabled", 1)),
        "language": normalize_language(col("language", 2)),
        "generate_title": bool(col("generate_title", 3)),
        "generate_description": bool(col("generate_description", 4)),
        "generate_hashtags": bool(col("generate_hashtags", 5)),
        "system_prompt": col("system_prompt", 6),
        "title_template": col("title_template", 7),
        "description_template": col("description_template", 8),
        "locked_hashtags": _parse_tags(col("locked_hashtags_json", 9)),
        "model_override": col("model_override", 10),
        "config_version": int(col("config_version", 11) or 1),
        "created_at": col("created_at", 12),
        "updated_at": col("updated_at", 13),
    }


def get_settings(pipeline_id: str) -> dict[str, Any]:
    row = (
        get_client()
        .execute(
            "SELECT pipeline_id, enabled, language, generate_title, "
            "generate_description, generate_hashtags, system_prompt, "
            "title_template, description_template, locked_hashtags_json, "
            "model_override, config_version, created_at, updated_at "
            "FROM drama_ai_settings WHERE pipeline_id = ?",
            (pipeline_id,),
        )
        .fetchone()
    )
    parsed = _row_to_settings(row)
    if parsed is not None:
        return parsed
    return default_settings(pipeline_id)


def upsert_settings(pipeline_id: str, **fields: Any) -> dict[str, Any]:
    current = get_settings(pipeline_id)
    expected = fields.pop("expected_config_version", None)
    if expected is not None and int(expected) != int(current.get("config_version") or 1):
        raise VersionConflict(int(expected), int(current.get("config_version") or 1))
    enabled = _bool(fields["enabled"]) if "enabled" in fields else current["enabled"]
    language = (
        normalize_language(fields["language"])
        if "language" in fields
        else current["language"]
    )
    generate_title = (
        _bool(fields["generate_title"])
        if "generate_title" in fields
        else current["generate_title"]
    )
    generate_description = (
        _bool(fields["generate_description"])
        if "generate_description" in fields
        else current["generate_description"]
    )
    generate_hashtags = (
        _bool(fields["generate_hashtags"])
        if "generate_hashtags" in fields
        else current["generate_hashtags"]
    )
    system_prompt = (
        (str(fields["system_prompt"]).strip() or None)
        if "system_prompt" in fields
        else current["system_prompt"]
    )
    title_template = (
        (str(fields["title_template"]).strip() or None)
        if "title_template" in fields
        else current["title_template"]
    )
    description_template = (
        (str(fields["description_template"]).strip() or None)
        if "description_template" in fields
        else current["description_template"]
    )
    locked = (
        _parse_tags(fields["locked_hashtags"])
        if "locked_hashtags" in fields
        else current["locked_hashtags"]
    )
    model_override = (
        (str(fields["model_override"]).strip() or None)
        if "model_override" in fields
        else current.get("model_override")
    )
    new_version = int(current.get("config_version") or 1) + 1
    conn = get_client()
    conn.execute(
        "INSERT INTO drama_ai_settings (pipeline_id, enabled, language, "
        "generate_title, generate_description, generate_hashtags, system_prompt, "
        "title_template, description_template, locked_hashtags_json, "
        "model_override, config_version, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), "
        "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')) "
        "ON CONFLICT(pipeline_id) DO UPDATE SET enabled=excluded.enabled, "
        "language=excluded.language, generate_title=excluded.generate_title, "
        "generate_description=excluded.generate_description, "
        "generate_hashtags=excluded.generate_hashtags, "
        "system_prompt=excluded.system_prompt, title_template=excluded.title_template, "
        "description_template=excluded.description_template, "
        "locked_hashtags_json=excluded.locked_hashtags_json, "
        "model_override=excluded.model_override, "
        "config_version=excluded.config_version, "
        "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now')",
        (
            pipeline_id,
            1 if enabled else 0,
            language,
            1 if generate_title else 0,
            1 if generate_description else 0,
            1 if generate_hashtags else 0,
            system_prompt,
            title_template,
            description_template,
            json.dumps(locked, ensure_ascii=False),
            model_override,
            new_version,
        ),
    )
    conn.commit()
    return get_settings(pipeline_id)


def reset_settings(pipeline_id: str) -> dict[str, Any]:
    """Restore factory defaults (AI off). Version still bumps to invalidate cache."""
    current = get_settings(pipeline_id)
    conn = get_client()
    conn.execute(
        "INSERT INTO drama_ai_settings (pipeline_id, enabled, language, "
        "generate_title, generate_description, generate_hashtags, system_prompt, "
        "title_template, description_template, locked_hashtags_json, "
        "model_override, config_version, created_at, updated_at) "
        "VALUES (?, 0, 'vi', 1, 1, 1, NULL, NULL, NULL, '[]', NULL, ?, "
        "strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), "
        "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')) "
        "ON CONFLICT(pipeline_id) DO UPDATE SET enabled=0, language='vi', "
        "generate_title=1, generate_description=1, generate_hashtags=1, "
        "system_prompt=NULL, title_template=NULL, description_template=NULL, "
        "locked_hashtags_json='[]', model_override=NULL, "
        "config_version=excluded.config_version, "
        "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now')",
        (pipeline_id, int(current.get("config_version") or 1) + 1),
    )
    conn.commit()
    return get_settings(pipeline_id)


def compute_config_hash(
    *,
    enabled: bool,
    language: str,
    generate_title: bool,
    generate_description: bool,
    generate_hashtags: bool,
    system_prompt: str | None,
    title_template: str | None,
    description_template: str | None,
    locked_hashtags: list[str] | None,
    model: str | None,
    config_version: int | None = None,
) -> str:
    canonical = json.dumps(
        {
            "enabled": bool(enabled),
            "language": normalize_language(language),
            "generate_title": bool(generate_title),
            "generate_description": bool(generate_description),
            "generate_hashtags": bool(generate_hashtags),
            "system_prompt": (system_prompt or "").strip(),
            "title_template": (title_template or "").strip(),
            "description_template": (description_template or "").strip(),
            "locked_hashtags": sorted(locked_hashtags or []),
            "model": (model or "").strip(),
            "config_version": int(config_version or 0),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def current_config_hash(pipeline_id: str, model: str | None = None) -> tuple[dict[str, Any], str]:
    cfg = get_settings(pipeline_id)
    effective_model = (cfg.get("model_override") or "").strip() or (model or "").strip()
    return cfg, compute_config_hash(
        enabled=cfg["enabled"],
        language=cfg["language"],
        generate_title=cfg["generate_title"],
        generate_description=cfg["generate_description"],
        generate_hashtags=cfg["generate_hashtags"],
        system_prompt=cfg.get("system_prompt"),
        title_template=cfg.get("title_template"),
        description_template=cfg.get("description_template"),
        locked_hashtags=cfg.get("locked_hashtags"),
        model=effective_model,
        config_version=cfg.get("config_version"),
    )


def source_hash(*parts: Any) -> str:
    joined = "\u0000".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


# ---- generation cache -------------------------------------------------------

def get_cache_row(job_id: str, language: str) -> dict[str, Any] | None:
    row = (
        get_client()
        .execute(
            "SELECT id, pipeline_id, series_id, job_id, language, config_hash, "
            "source_hash, model, title, description, hashtags_json, status, generated_at "
            "FROM drama_ai_metadata_cache WHERE job_id = ? AND language = ? "
            "ORDER BY generated_at DESC LIMIT 1",
            (job_id, normalize_language(language)),
        )
        .fetchone()
    )
    if row is None:
        return None
    out = dict(row) if hasattr(row, "keys") else None
    if out is None:
        try:
            out = {
                "id": row[0], "pipeline_id": row[1], "series_id": row[2],
                "job_id": row[3], "language": row[4], "config_hash": row[5],
                "source_hash": row[6], "model": row[7], "title": row[8],
                "description": row[9], "hashtags_json": row[10],
                "status": row[11], "generated_at": row[12],
            }
        except Exception:
            return None
    try:
        out["hashtags"] = json.loads(out.get("hashtags_json") or "[]")
        if not isinstance(out["hashtags"], list):
            out["hashtags"] = []
    except Exception:
        out["hashtags"] = []
    return out


def upsert_cache(
    *,
    pipeline_id: str,
    series_id: str,
    job_id: str,
    language: str,
    config_hash: str,
    source_hash: str,
    model: str,
    title: str,
    description: str,
    hashtags: list[str],
    status: str = "generated",
    cache_id: str | None = None,
) -> dict[str, Any]:
    import uuid

    cid = cache_id or f"daic_{uuid.uuid4().hex[:12]}"
    conn = get_client()
    conn.execute(
        "INSERT INTO drama_ai_metadata_cache (id, pipeline_id, series_id, job_id, "
        "language, config_hash, source_hash, model, title, description, "
        "hashtags_json, status, generated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')) "
        "ON CONFLICT(id) DO UPDATE SET title=excluded.title, "
        "description=excluded.description, hashtags_json=excluded.hashtags_json, "
        "config_hash=excluded.config_hash, source_hash=excluded.source_hash, "
        "model=excluded.model, status=excluded.status, "
        "generated_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now')",
        (
            cid, pipeline_id, series_id, job_id, normalize_language(language),
            config_hash, source_hash, model, title, description,
            json.dumps(hashtags or [], ensure_ascii=False), status,
        ),
    )
    conn.commit()
    row = get_cache_row(job_id, language)
    assert row is not None
    return row
