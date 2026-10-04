from typing import Any

from ..client import get_client


async def create_pipeline(
    *,
    pipeline_id: str,
    name: str,
    slug: str,
    enabled: bool = True,
    auto_publish: bool = True,
) -> dict[str, Any]:
    client = get_client()
    await client.execute(
        """
        INSERT INTO facebook_pipelines (id, name, slug, enabled, auto_publish)
        VALUES (:id, :name, :slug, :enabled, :auto_publish)
        """,
        {
            "id": pipeline_id,
            "name": name,
            "slug": slug,
            "enabled": 1 if enabled else 0,
            "auto_publish": 1 if auto_publish else 0,
        },
    )
    return {
        "id": pipeline_id,
        "name": name,
        "slug": slug,
        "enabled": enabled,
        "auto_publish": auto_publish,
    }


async def get_pipeline(pipeline_id: str) -> dict[str, Any] | None:
    client = get_client()
    rows = await client.execute(
        "SELECT id, name, slug, enabled, auto_publish, created_at, updated_at FROM facebook_pipelines WHERE id = :id",
        {"id": pipeline_id},
    )
    if not rows.rows:
        return None
    r = rows.rows[0]
    return {
        "id": r[0],
        "name": r[1],
        "slug": r[2],
        "enabled": bool(r[3]),
        "auto_publish": bool(r[4]),
        "created_at": r[5],
        "updated_at": r[6],
    }


async def get_pipeline_by_slug(slug: str) -> dict[str, Any] | None:
    client = get_client()
    rows = await client.execute(
        "SELECT id, name, slug, enabled, auto_publish, created_at, updated_at FROM facebook_pipelines WHERE slug = :slug",
        {"slug": slug},
    )
    if not rows.rows:
        return None
    r = rows.rows[0]
    return {
        "id": r[0],
        "name": r[1],
        "slug": r[2],
        "enabled": bool(r[3]),
        "auto_publish": bool(r[4]),
        "created_at": r[5],
        "updated_at": r[6],
    }


async def list_pipelines() -> list[dict[str, Any]]:
    client = get_client()
    rows = await client.execute(
        "SELECT id, name, slug, enabled, auto_publish, created_at, updated_at FROM facebook_pipelines ORDER BY created_at"
    )
    return [
        {
            "id": r[0],
            "name": r[1],
            "slug": r[2],
            "enabled": bool(r[3]),
            "auto_publish": bool(r[4]),
            "created_at": r[5],
            "updated_at": r[6],
        }
        for r in rows.rows
    ]
