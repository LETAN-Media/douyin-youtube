from typing import Any

from ...db.client import execute, result_to_dict, result_to_dicts


async def create_pipeline(
    pipeline_id: str,
    name: str,
    slug: str,
    auto_publish: bool = True,
) -> dict[str, Any]:
    await execute(
        """
        INSERT INTO tiktok_pipelines (id, name, slug, auto_publish)
        VALUES (:id, :name, :slug, :auto_publish)
        """,
        {"id": pipeline_id, "name": name, "slug": slug, "auto_publish": 1 if auto_publish else 0},
    )
    row = await get_pipeline(pipeline_id)
    assert row is not None
    return row


async def get_pipeline(pipeline_id: str) -> dict[str, Any] | None:
    res = await execute(
        "SELECT id, name, slug, enabled, auto_publish, created_at, updated_at "
        "FROM tiktok_pipelines WHERE id = :id",
        {"id": pipeline_id},
    )
    return result_to_dict(res)


async def list_pipelines() -> list[dict[str, Any]]:
    res = await execute(
        "SELECT id, name, slug, enabled, auto_publish, created_at, updated_at "
        "FROM tiktok_pipelines ORDER BY created_at"
    )
    return result_to_dicts(res)


async def update_pipeline_enable(pipeline_id: str, enabled: bool) -> dict[str, Any] | None:
    await execute(
        "UPDATE tiktok_pipelines SET enabled = :enabled, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = :id",
        {"id": pipeline_id, "enabled": 1 if enabled else 0},
    )
    return await get_pipeline(pipeline_id)


async def update_pipeline_auto_publish(pipeline_id: str, auto_publish: bool) -> dict[str, Any] | None:
    await execute(
        "UPDATE tiktok_pipelines SET auto_publish = :auto_publish, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = :id",
        {"id": pipeline_id, "auto_publish": 1 if auto_publish else 0},
    )
    return await get_pipeline(pipeline_id)


async def get_pipeline_by_slug(slug: str) -> dict[str, Any] | None:
    res = await execute(
        "SELECT id, name, slug, enabled, auto_publish, created_at, updated_at "
        "FROM tiktok_pipelines WHERE slug = :slug",
        {"slug": slug},
    )
    return result_to_dict(res)
