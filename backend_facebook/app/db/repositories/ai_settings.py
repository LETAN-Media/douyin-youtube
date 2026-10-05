"""AI settings persistence per pipeline (Task 9).

Stores custom AI instructions, templates, locked hashtags, and enabled flag.
No credentials or ToolNet API keys are stored here.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from ..client import get_client

DEFAULT_ENABLED = True
DEFAULT_SYSTEM_PROMPT = ""
DEFAULT_TITLE_TEMPLATE = "{title}"
DEFAULT_DESCRIPTION_TEMPLATE = "{description}\n\n{hashtags}"
DEFAULT_LOCKED_HASHTAGS: list[str] = []
DEFAULT_LANGUAGE = "vi"


def normalize_hashtag(raw: str) -> str:
    tag = str(raw or "").strip()
    if not tag.startswith("#"):
        tag = "#" + tag.lstrip("#")
    tag = "#" + re.sub(r"\s+", "", tag[1:])
    return tag


def normalize_locked_hashtags(raw: list[str] | None) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for item in raw or []:
        tag = normalize_hashtag(item)
        lower = tag.lower()
        if tag != "#" and lower not in seen:
            seen.add(lower)
            tags.append(tag)
    return tags[:30]


def compute_config_hash(
    *,
    enabled: bool,
    system_prompt: str | None,
    title_template: str | None,
    description_template: str | None,
    locked_hashtags: list[str] | None,
    language: str | None,
    model: str | None = None,
) -> str:
    norm_enabled = "1" if enabled else "0"
    norm_sys = (system_prompt or "").strip()
    norm_title = (title_template or "").strip()
    norm_desc = (description_template or "").strip()
    norm_tags = json.dumps(sorted([h.lower() for h in normalize_locked_hashtags(locked_hashtags)]))
    norm_lang = (language or "vi").strip().lower()
    norm_model = (model or "").strip()
    material = f"{norm_enabled}|{norm_sys}|{norm_title}|{norm_desc}|{norm_tags}|{norm_lang}|{norm_model}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def default_settings(pipeline_id: str, model: str | None = None) -> dict[str, Any]:
    return {
        "pipeline_id": pipeline_id,
        "enabled": DEFAULT_ENABLED,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "title_template": DEFAULT_TITLE_TEMPLATE,
        "description_template": DEFAULT_DESCRIPTION_TEMPLATE,
        "locked_hashtags": list(DEFAULT_LOCKED_HASHTAGS),
        "language": DEFAULT_LANGUAGE,
        "config_hash": compute_config_hash(
            enabled=DEFAULT_ENABLED,
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            title_template=DEFAULT_TITLE_TEMPLATE,
            description_template=DEFAULT_DESCRIPTION_TEMPLATE,
            locked_hashtags=DEFAULT_LOCKED_HASHTAGS,
            language=DEFAULT_LANGUAGE,
            model=model,
        ),
        "created_at": None,
        "updated_at": None,
    }


def _row_to_dict(r: Any) -> dict[str, Any]:
    locked_hashtags: list[str] = []
    try:
        parsed = json.loads(r[5]) if r[5] else []
        if isinstance(parsed, list):
            locked_hashtags = normalize_locked_hashtags([str(h) for h in parsed])
    except Exception:
        locked_hashtags = []

    return {
        "pipeline_id": r[0],
        "enabled": bool(r[1]),
        "system_prompt": r[2] or "",
        "title_template": r[3] or DEFAULT_TITLE_TEMPLATE,
        "description_template": r[4] or DEFAULT_DESCRIPTION_TEMPLATE,
        "locked_hashtags": locked_hashtags,
        "language": r[6] or DEFAULT_LANGUAGE,
        "config_hash": r[7],
        "created_at": r[8],
        "updated_at": r[9],
    }


async def get_settings(pipeline_id: str, model: str | None = None) -> dict[str, Any]:
    client = get_client()
    rows = await client.execute(
        """
        SELECT pipeline_id, enabled, system_prompt, title_template,
               description_template, locked_hashtags_json, language,
               config_hash, created_at, updated_at
        FROM facebook_ai_settings
        WHERE pipeline_id = :id
        """,
        {"id": pipeline_id},
    )
    if not rows.rows:
        return default_settings(pipeline_id, model=model)
    data = _row_to_dict(rows.rows[0])
    if not data.get("config_hash"):
        data["config_hash"] = compute_config_hash(
            enabled=data["enabled"],
            system_prompt=data["system_prompt"],
            title_template=data["title_template"],
            description_template=data["description_template"],
            locked_hashtags=data["locked_hashtags"],
            language=data["language"],
            model=model,
        )
    return data


async def current_config_hash(
    pipeline_id: str, *, model: str | None = None
) -> tuple[dict[str, Any], str]:
    """Load settings plus the canonical config hash for scheduling decisions.

    The hash is ALWAYS recomputed from live fields + the live ToolNet model.
    The stored ``config_hash`` is never trusted here: legacy rows may carry
    a model-less hash (written before the model was included), and trusting
    it makes the worker see a false cache-hit while the scheduler — which
    recomputes — sees zero AI-ready reels. That combination stalls the
    pipeline silently with no errors.
    """
    from ...config import settings as app_settings

    live_model = (model if model is not None else (app_settings.TOOLNET_MODEL or "")).strip()
    data = await get_settings(pipeline_id, model=live_model or None)
    canonical = compute_config_hash(
        enabled=data.get("enabled", True),
        system_prompt=data.get("system_prompt"),
        title_template=data.get("title_template"),
        description_template=data.get("description_template"),
        locked_hashtags=data.get("locked_hashtags"),
        language=data.get("language"),
        model=live_model,
    )
    return data, canonical


async def upsert_settings(
    *,
    pipeline_id: str,
    enabled: bool,
    system_prompt: str,
    title_template: str,
    description_template: str,
    locked_hashtags: list[str],
    language: str,
    model: str | None = None,
) -> dict[str, Any]:
    client = get_client()
    clean_tags = normalize_locked_hashtags(locked_hashtags)
    config_hash = compute_config_hash(
        enabled=enabled,
        system_prompt=system_prompt,
        title_template=title_template,
        description_template=description_template,
        locked_hashtags=clean_tags,
        language=language,
        model=model,
    )
    await client.execute(
        """
        INSERT INTO facebook_ai_settings
            (pipeline_id, enabled, system_prompt, title_template,
             description_template, locked_hashtags_json, language,
             config_hash, created_at, updated_at)
        VALUES
            (:pipeline_id, :enabled, :system_prompt, :title_template,
             :description_template, :locked_hashtags_json, :language,
             :config_hash, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        ON CONFLICT(pipeline_id) DO UPDATE SET
            enabled = excluded.enabled,
            system_prompt = excluded.system_prompt,
            title_template = excluded.title_template,
            description_template = excluded.description_template,
            locked_hashtags_json = excluded.locked_hashtags_json,
            language = excluded.language,
            config_hash = excluded.config_hash,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        """,
        {
            "pipeline_id": pipeline_id,
            "enabled": 1 if enabled else 0,
            "system_prompt": system_prompt,
            "title_template": title_template,
            "description_template": description_template,
            "locked_hashtags_json": json.dumps(clean_tags, ensure_ascii=False),
            "language": language,
            "config_hash": config_hash,
        },
    )
    return await get_settings(pipeline_id, model=model)
