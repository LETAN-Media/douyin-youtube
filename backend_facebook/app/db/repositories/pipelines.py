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


async def update_pipeline(
    pipeline_id: str,
    *,
    enabled: bool | None = None,
    auto_publish: bool | None = None,
    name: str | None = None,
) -> dict[str, Any] | None:
    """Partial update: only the fields explicitly provided are changed.

    Slug is never touched here (URLs/labels keep working). Empty names are
    rejected with ValueError. Returns the updated row, or None when the
    pipeline does not exist (or nothing was provided).
    """
    sets: list[str] = []
    params: dict[str, Any] = {"id": pipeline_id}
    if enabled is not None:
        sets.append("enabled = :enabled")
        params["enabled"] = 1 if enabled else 0
    if auto_publish is not None:
        sets.append("auto_publish = :auto_publish")
        params["auto_publish"] = 1 if auto_publish else 0
    if name is not None:
        clean = name.strip()
        if not clean:
            raise ValueError("Pipeline name must not be empty.")
        if len(clean) > 200:
            raise ValueError("Pipeline name is too long (max 200).")
        sets.append("name = :name")
        params["name"] = clean
    if not sets:
        return await get_pipeline(pipeline_id)
    client = get_client()
    res = await client.execute(
        f"UPDATE facebook_pipelines SET {', '.join(sets)}, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = :id",
        params,
    )
    if (res.rows_affected or 0) == 0:
        return None
    updated = await get_pipeline(pipeline_id)
    assert updated is not None
    return updated


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
