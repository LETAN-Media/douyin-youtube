from typing import Any

from ...db.client import execute, result_to_dict, result_to_dicts

YOUTUBE_UPLOAD_MODES = {"shorts", "video", "both"}


def normalize_upload_mode(value: Any) -> str:
    if not value or not isinstance(value, str):
        return "shorts"
    norm = value.lower().strip()
    if norm not in YOUTUBE_UPLOAD_MODES:
        raise ValueError(
            f"Invalid youtube_upload_mode: {value!r}. Expected one of {sorted(YOUTUBE_UPLOAD_MODES)}."
        )
    return norm


async def create_pipeline(
    pipeline_id: str,
    name: str,
    slug: str,
    auto_publish: bool = True,
    youtube_upload_mode: str = "shorts",
) -> dict[str, Any]:
    norm_mode = normalize_upload_mode(youtube_upload_mode)
    await execute(
        """
        INSERT INTO tiktok_pipelines (id, name, slug, auto_publish, youtube_upload_mode)
        VALUES (:id, :name, :slug, :auto_publish, :youtube_upload_mode)
        """,
        {
            "id": pipeline_id,
            "name": name,
            "slug": slug,
            "auto_publish": 1 if auto_publish else 0,
            "youtube_upload_mode": norm_mode,
        },
    )
    row = await get_pipeline(pipeline_id)
    assert row is not None
    return row


async def get_pipeline(pipeline_id: str) -> dict[str, Any] | None:
    res = await execute(
        "SELECT id, name, slug, enabled, auto_publish, youtube_upload_mode, created_at, updated_at "
        "FROM tiktok_pipelines WHERE id = :id",
        {"id": pipeline_id},
    )
    row = result_to_dict(res)
    if row and not row.get("youtube_upload_mode"):
        row["youtube_upload_mode"] = "shorts"
    return row


async def list_pipelines() -> list[dict[str, Any]]:
    res = await execute(
        "SELECT id, name, slug, enabled, auto_publish, youtube_upload_mode, created_at, updated_at "
        "FROM tiktok_pipelines ORDER BY created_at"
    )
    rows = result_to_dicts(res)
    for r in rows:
        if not r.get("youtube_upload_mode"):
            r["youtube_upload_mode"] = "shorts"
    return rows


async def update_pipeline(
    pipeline_id: str,
    *,
    name: str | None = None,
    enabled: bool | None = None,
    auto_publish: bool | None = None,
    youtube_upload_mode: str | None = None,
) -> dict[str, Any] | None:
    sets = ["updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"]
    params: dict[str, Any] = {"id": pipeline_id}

    if name is not None:
        sets.append("name = :name")
        params["name"] = name.strip()
    if enabled is not None:
        sets.append("enabled = :enabled")
        params["enabled"] = 1 if enabled else 0
    if auto_publish is not None:
        sets.append("auto_publish = :auto_publish")
        params["auto_publish"] = 1 if auto_publish else 0
    if youtube_upload_mode is not None:
        sets.append("youtube_upload_mode = :youtube_upload_mode")
        params["youtube_upload_mode"] = normalize_upload_mode(youtube_upload_mode)

    await execute(
        f"UPDATE tiktok_pipelines SET {', '.join(sets)} WHERE id = :id",
        params,
    )
    return await get_pipeline(pipeline_id)


async def update_pipeline_enable(pipeline_id: str, enabled: bool) -> dict[str, Any] | None:
    return await update_pipeline(pipeline_id, enabled=enabled)


async def update_pipeline_auto_publish(pipeline_id: str, auto_publish: bool) -> dict[str, Any] | None:
    return await update_pipeline(pipeline_id, auto_publish=auto_publish)


async def get_pipeline_by_slug(slug: str) -> dict[str, Any] | None:
    res = await execute(
        "SELECT id, name, slug, enabled, auto_publish, youtube_upload_mode, created_at, updated_at "
        "FROM tiktok_pipelines WHERE slug = :slug",
        {"slug": slug},
    )
    row = result_to_dict(res)
    if row and not row.get("youtube_upload_mode"):
        row["youtube_upload_mode"] = "shorts"
    return row
