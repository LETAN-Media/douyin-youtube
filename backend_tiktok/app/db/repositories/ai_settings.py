from typing import Any

from ...db.client import execute, result_to_dict, result_to_dicts


async def get_ai_settings(pipeline_id: str) -> dict[str, Any] | None:
    res = await execute(
        "SELECT pipeline_id, enabled, system_prompt, title_template, description_template, "
        "locked_hashtags_json, language, model, config_hash, created_at, updated_at "
        "FROM tiktok_ai_settings WHERE pipeline_id = :pid",
        {"pid": pipeline_id},
    )
    return result_to_dict(res)


async def create_or_update_ai_settings(
    pipeline_id: str,
    enabled: bool | None = None,
    system_prompt: str | None = None,
    title_template: str | None = None,
    description_template: str | None = None,
    locked_hashtags_json: str | None = None,
    language: str | None = None,
    model: str | None = None,
    config_hash: str | None = None,
) -> dict[str, Any]:
    row = await get_ai_settings(pipeline_id)
    if row is None:
        await execute(
            """
            INSERT INTO tiktok_ai_settings
                (pipeline_id, enabled, system_prompt, title_template,
                 description_template, locked_hashtags_json, language, model, config_hash)
            VALUES
                (:pid, :enabled, :system_prompt, :title_template,
                 :description_template, :locked_hashtags_json, :language, :model, :config_hash)
            """,
            {
                "pid": pipeline_id,
                "enabled": 1 if enabled else 0,
                "system_prompt": system_prompt,
                "title_template": title_template,
                "description_template": description_template,
                "locked_hashtags_json": locked_hashtags_json or "[]",
                "language": language or "vi",
                "model": model,
                "config_hash": config_hash,
            },
        )
    else:
        cols: list[str] = []
        params: dict[str, Any] = {"pid": pipeline_id}
        field_map = {
            "enabled": enabled,
            "system_prompt": system_prompt,
            "title_template": title_template,
            "description_template": description_template,
            "locked_hashtags_json": locked_hashtags_json,
            "language": language,
            "model": model,
            "config_hash": config_hash,
        }
        for k, v in field_map.items():
            if v is not None:
                cols.append(f"{k} = :{k}")
                params[k] = v if k != "enabled" else (1 if v else 0)
        cols.append("updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')")
        await execute(
            f"UPDATE tiktok_ai_settings SET {', '.join(cols)} WHERE pipeline_id = :pid",
            params,
        )
    return await get_ai_settings(pipeline_id)  # type: ignore[return-value]


async def list_pipelines_with_ai() -> list[dict[str, Any]]:
    res = await execute(
        "SELECT pipeline_id FROM tiktok_ai_settings WHERE enabled = 1"
    )
    return result_to_dicts(res)
