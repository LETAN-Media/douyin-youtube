import json
from typing import Any

from ...db.client import execute, result_to_dict, result_to_dicts

DEFAULT_AI_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "provider": "toolnet",
    "model": "groq/openai/gpt-oss-120b",
    "system_prompt": "Bạn là chuyên gia sáng tạo nội dung YouTube Shorts hàng đầu. Hãy viết tiêu đề, mô tả và hashtag hấp dẫn, tối ưu hóa SEO và giữ chân người xem.",
    "title_prompt": "Viết tiêu đề ngắn gọn (dưới 80 ký tự), kích thích sự tò mò, chứa từ khóa chính.",
    "description_prompt": "Viết mô tả 2-3 câu ngắn gọn về nội dung video, kèm lời kêu gọi like và subscribe.",
    "hashtag_prompt": "Chọn các hashtag thịnh hành, liên quan mật thiết đến chủ đề video.",
    "title_template": "{title}",
    "description_template": "{description}\n\n{hashtags}",
    "locked_hashtags": [],
    "language": "vi",
    "max_hashtags": 10,
    "include_emojis": True,
    "tone": "engaging",
    "required_keywords": "",
    "forbidden_keywords": "",
}


def _normalize_row(row: dict[str, Any] | None, pipeline_id: str) -> dict[str, Any]:
    if not row:
        return {**DEFAULT_AI_SETTINGS, "pipeline_id": pipeline_id}

    raw_tags = row.get("locked_hashtags_json") or "[]"
    try:
        locked_hashtags = json.loads(raw_tags) if isinstance(raw_tags, str) else list(raw_tags)
    except Exception:
        locked_hashtags = []

    return {
        "pipeline_id": pipeline_id,
        "enabled": bool(row.get("enabled", 1)),
        "provider": row.get("provider") or DEFAULT_AI_SETTINGS["provider"],
        "model": row.get("model") or DEFAULT_AI_SETTINGS["model"],
        "system_prompt": row.get("system_prompt") if row.get("system_prompt") is not None else DEFAULT_AI_SETTINGS["system_prompt"],
        "title_prompt": row.get("title_prompt") if row.get("title_prompt") is not None else DEFAULT_AI_SETTINGS["title_prompt"],
        "description_prompt": row.get("description_prompt") if row.get("description_prompt") is not None else DEFAULT_AI_SETTINGS["description_prompt"],
        "hashtag_prompt": row.get("hashtag_prompt") if row.get("hashtag_prompt") is not None else DEFAULT_AI_SETTINGS["hashtag_prompt"],
        "title_template": row.get("title_template") if row.get("title_template") is not None else DEFAULT_AI_SETTINGS["title_template"],
        "description_template": row.get("description_template") if row.get("description_template") is not None else DEFAULT_AI_SETTINGS["description_template"],
        "locked_hashtags": locked_hashtags,
        "language": row.get("language") or DEFAULT_AI_SETTINGS["language"],
        "max_hashtags": int(row.get("max_hashtags") or 10),
        "include_emojis": bool(row.get("include_emojis", 1)),
        "tone": row.get("tone") or DEFAULT_AI_SETTINGS["tone"],
        "required_keywords": row.get("required_keywords") or "",
        "forbidden_keywords": row.get("forbidden_keywords") or "",
        "config_hash": row.get("config_hash"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


async def get_ai_settings(pipeline_id: str) -> dict[str, Any]:
    res = await execute(
        "SELECT pipeline_id, enabled, provider, model, system_prompt, title_prompt, "
        "description_prompt, hashtag_prompt, title_template, description_template, "
        "locked_hashtags_json, language, max_hashtags, include_emojis, tone, "
        "required_keywords, forbidden_keywords, config_hash, created_at, updated_at "
        "FROM tiktok_ai_settings WHERE pipeline_id = :pid",
        {"pid": pipeline_id},
    )
    row = result_to_dict(res)
    return _normalize_row(row, pipeline_id)


async def create_or_update_ai_settings(
    pipeline_id: str,
    enabled: bool | None = None,
    provider: str | None = None,
    model: str | None = None,
    system_prompt: str | None = None,
    title_prompt: str | None = None,
    description_prompt: str | None = None,
    hashtag_prompt: str | None = None,
    title_template: str | None = None,
    description_template: str | None = None,
    locked_hashtags: list[str] | None = None,
    locked_hashtags_json: str | None = None,
    language: str | None = None,
    max_hashtags: int | None = None,
    include_emojis: bool | None = None,
    tone: str | None = None,
    required_keywords: str | None = None,
    forbidden_keywords: str | None = None,
    config_hash: str | None = None,
) -> dict[str, Any]:
    tags_json = (
        json.dumps(locked_hashtags)
        if locked_hashtags is not None
        else (locked_hashtags_json if locked_hashtags_json is not None else None)
    )

    existing = await execute(
        "SELECT pipeline_id FROM tiktok_ai_settings WHERE pipeline_id = :pid",
        {"pid": pipeline_id},
    )
    if not existing.rows:
        await execute(
            """
            INSERT INTO tiktok_ai_settings
                (pipeline_id, enabled, provider, model, system_prompt, title_prompt,
                 description_prompt, hashtag_prompt, title_template, description_template,
                 locked_hashtags_json, language, max_hashtags, include_emojis, tone,
                 required_keywords, forbidden_keywords, config_hash)
            VALUES
                (:pid, :enabled, :provider, :model, :system_prompt, :title_prompt,
                 :description_prompt, :hashtag_prompt, :title_template, :description_template,
                 :locked_hashtags_json, :language, :max_hashtags, :include_emojis, :tone,
                 :required_keywords, :forbidden_keywords, :config_hash)
            """,
            {
                "pid": pipeline_id,
                "enabled": 1 if (enabled if enabled is not None else DEFAULT_AI_SETTINGS["enabled"]) else 0,
                "provider": provider or DEFAULT_AI_SETTINGS["provider"],
                "model": model or DEFAULT_AI_SETTINGS["model"],
                "system_prompt": system_prompt if system_prompt is not None else DEFAULT_AI_SETTINGS["system_prompt"],
                "title_prompt": title_prompt if title_prompt is not None else DEFAULT_AI_SETTINGS["title_prompt"],
                "description_prompt": description_prompt if description_prompt is not None else DEFAULT_AI_SETTINGS["description_prompt"],
                "hashtag_prompt": hashtag_prompt if hashtag_prompt is not None else DEFAULT_AI_SETTINGS["hashtag_prompt"],
                "title_template": title_template if title_template is not None else DEFAULT_AI_SETTINGS["title_template"],
                "description_template": description_template if description_template is not None else DEFAULT_AI_SETTINGS["description_template"],
                "locked_hashtags_json": tags_json if tags_json is not None else "[]",
                "language": language or DEFAULT_AI_SETTINGS["language"],
                "max_hashtags": max_hashtags if max_hashtags is not None else DEFAULT_AI_SETTINGS["max_hashtags"],
                "include_emojis": 1 if (include_emojis if include_emojis is not None else DEFAULT_AI_SETTINGS["include_emojis"]) else 0,
                "tone": tone or DEFAULT_AI_SETTINGS["tone"],
                "required_keywords": required_keywords or "",
                "forbidden_keywords": forbidden_keywords or "",
                "config_hash": config_hash,
            },
        )
    else:
        cols: list[str] = []
        params: dict[str, Any] = {"pid": pipeline_id}
        field_map = {
            "enabled": (1 if enabled else 0) if enabled is not None else None,
            "provider": provider,
            "model": model,
            "system_prompt": system_prompt,
            "title_prompt": title_prompt,
            "description_prompt": description_prompt,
            "hashtag_prompt": hashtag_prompt,
            "title_template": title_template,
            "description_template": description_template,
            "locked_hashtags_json": tags_json,
            "language": language,
            "max_hashtags": max_hashtags,
            "include_emojis": (1 if include_emojis else 0) if include_emojis is not None else None,
            "tone": tone,
            "required_keywords": required_keywords,
            "forbidden_keywords": forbidden_keywords,
            "config_hash": config_hash,
        }
        for k, v in field_map.items():
            if v is not None:
                cols.append(f"{k} = :{k}")
                params[k] = v
        cols.append("updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')")
        if cols:
            await execute(
                f"UPDATE tiktok_ai_settings SET {', '.join(cols)} WHERE pipeline_id = :pid",
                params,
            )
    return await get_ai_settings(pipeline_id)


async def list_pipelines_with_ai() -> list[dict[str, Any]]:
    res = await execute(
        "SELECT pipeline_id FROM tiktok_ai_settings WHERE enabled = 1"
    )
    return result_to_dicts(res)
