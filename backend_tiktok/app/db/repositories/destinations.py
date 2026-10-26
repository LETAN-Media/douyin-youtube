from typing import Any

from ...db.client import execute, result_to_dict, result_to_dicts


async def create_destination(
    destination_id: str,
    pipeline_id: str,
    channel_id: str | None = None,
    channel_name: str | None = None,
    account_id: str | None = None,
    visibility: str = "public",
) -> dict[str, Any]:
    await execute(
        """
        INSERT INTO youtube_destinations
            (id, pipeline_id, account_id, channel_id, channel_name, visibility)
        VALUES
            (:id, :pipeline_id, :account_id, :channel_id, :channel_name, :visibility)
        """,
        {
            "id": destination_id,
            "pipeline_id": pipeline_id,
            "account_id": account_id,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "visibility": visibility,
        },
    )
    row = await get_destination(destination_id)
    assert row is not None
    return row


async def get_destination(destination_id: str) -> dict[str, Any] | None:
    res = await execute(
        "SELECT id, pipeline_id, account_id, channel_id, channel_name, visibility, "
        "enabled, connected, connected_at, created_at, updated_at "
        "FROM youtube_destinations WHERE id = :id",
        {"id": destination_id},
    )
    return result_to_dict(res)


async def list_destinations(pipeline_id: str) -> list[dict[str, Any]]:
    res = await execute(
        "SELECT id, pipeline_id, account_id, channel_id, channel_name, visibility, "
        "enabled, connected, connected_at, created_at, updated_at "
        "FROM youtube_destinations WHERE pipeline_id = :pipeline_id ORDER BY created_at",
        {"pipeline_id": pipeline_id},
    )
    return result_to_dicts(res)


async def update_destination_connected(
    destination_id: str, connected: bool, account_id: str | None = None
) -> None:
    await execute(
        "UPDATE youtube_destinations SET connected = :connected, "
        "connected_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), "
        "account_id = COALESCE(:account_id, account_id), "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = :id",
        {"id": destination_id, "connected": 1 if connected else 0, "account_id": account_id},
    )


async def update_destination(destination_id: str, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = :{k}" for k in fields)
    params = dict(fields)
    params["id"] = destination_id
    await execute(
        f"UPDATE youtube_destinations SET {cols}, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        params,
    )
