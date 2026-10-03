from typing import Any

from ..client import get_client


async def create_destination(
    *,
    destination_id: str,
    pipeline_id: str,
    channel_id: str,
    channel_name: str,
    visibility: str = "public",
    enabled: bool = True,
) -> dict[str, Any]:
    client = get_client()
    await client.execute(
        """
        INSERT INTO youtube_destinations (id, pipeline_id, channel_id, channel_name, visibility, enabled)
        VALUES (:id, :pipeline_id, :channel_id, :channel_name, :visibility, :enabled)
        """,
        {
            "id": destination_id,
            "pipeline_id": pipeline_id,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "visibility": visibility,
            "enabled": 1 if enabled else 0,
        },
    )
    return {
        "id": destination_id,
        "pipeline_id": pipeline_id,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "visibility": visibility,
        "enabled": enabled,
    }


async def get_destination(destination_id: str) -> dict[str, Any] | None:
    client = get_client()
    rows = await client.execute(
        "SELECT id, pipeline_id, channel_id, channel_name, visibility, enabled, created_at, updated_at FROM youtube_destinations WHERE id = :id",
        {"id": destination_id},
    )
    if not rows.rows:
        return None
    r = rows.rows[0]
    return {
        "id": r[0],
        "pipeline_id": r[1],
        "channel_id": r[2],
        "channel_name": r[3],
        "visibility": r[4],
        "enabled": bool(r[5]),
        "created_at": r[6],
        "updated_at": r[7],
    }


async def list_destinations(pipeline_id: str) -> list[dict[str, Any]]:
    client = get_client()
    rows = await client.execute(
        "SELECT id, pipeline_id, channel_id, channel_name, visibility, enabled, created_at, updated_at FROM youtube_destinations WHERE pipeline_id = :pipeline_id",
        {"pipeline_id": pipeline_id},
    )
    return [
        {
            "id": r[0],
            "pipeline_id": r[1],
            "channel_id": r[2],
            "channel_name": r[3],
            "visibility": r[4],
            "enabled": bool(r[5]),
            "created_at": r[6],
            "updated_at": r[7],
        }
        for r in rows.rows
    ]
