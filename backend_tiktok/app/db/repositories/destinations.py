from typing import Any

from ...db.client import execute, result_to_dict, result_to_dicts

_COLUMNS = (
    "id, pipeline_id, account_id, channel_id, channel_name, channel_avatar_url, "
    "visibility, enabled, connected, connected_at, is_default, created_at, updated_at"
)


def to_safe_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    d["enabled"] = bool(d.get("enabled", 0))
    d["connected"] = bool(d.get("connected", 0))
    d["is_default"] = bool(d.get("is_default", 0))
    return d


async def create_destination(
    destination_id: str,
    pipeline_id: str,
    channel_id: str | None = None,
    channel_name: str | None = None,
    channel_avatar_url: str | None = None,
    account_id: str | None = None,
    visibility: str = "public",
    enabled: bool = True,
    is_default: bool = False,
    connected: bool = False,
) -> dict[str, Any]:
    # If no other destination exists for this pipeline, make this one default
    existing_count_res = await execute(
        "SELECT COUNT(*) as count FROM youtube_destinations WHERE pipeline_id = :pipeline_id",
        {"pipeline_id": pipeline_id},
    )
    existing_count = 0
    row = result_to_dict(existing_count_res)
    if row:
        existing_count = row.get("count", 0)
    should_be_default = is_default or (existing_count == 0)

    await execute(
        f"""
        INSERT INTO youtube_destinations
            (id, pipeline_id, account_id, channel_id, channel_name, channel_avatar_url,
             visibility, enabled, connected, is_default)
        VALUES
            (:id, :pipeline_id, :account_id, :channel_id, :channel_name, :channel_avatar_url,
             :visibility, :enabled, :connected, :is_default)
        """,
        {
            "id": destination_id,
            "pipeline_id": pipeline_id,
            "account_id": account_id,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "channel_avatar_url": channel_avatar_url,
            "visibility": visibility,
            "enabled": 1 if enabled else 0,
            "connected": 1 if connected else 0,
            "is_default": 1 if should_be_default else 0,
        },
    )
    dest = await get_destination(destination_id)
    assert dest is not None
    return dest


async def get_destination(destination_id: str) -> dict[str, Any] | None:
    res = await execute(
        f"SELECT {_COLUMNS} FROM youtube_destinations WHERE id = :id",
        {"id": destination_id},
    )
    row = result_to_dict(res)
    return to_safe_dict(row)


async def list_destinations(pipeline_id: str) -> list[dict[str, Any]]:
    res = await execute(
        f"SELECT {_COLUMNS} FROM youtube_destinations "
        "WHERE pipeline_id = :pipeline_id ORDER BY is_default DESC, created_at ASC",
        {"pipeline_id": pipeline_id},
    )
    rows = result_to_dicts(res)
    return [to_safe_dict(r) for r in rows if r is not None]


async def set_destination_connected(
    destination_id: str,
    channel_id: str,
    channel_name: str,
    channel_avatar_url: str | None = None,
    account_id: str | None = None,
) -> dict[str, Any] | None:
    current = await get_destination(destination_id)
    if current is None:
        return None

    pipeline_id = current["pipeline_id"]
    # Check if there's any default destination in this pipeline
    default_res = await execute(
        "SELECT id FROM youtube_destinations WHERE pipeline_id = :pipeline_id AND is_default = 1",
        {"pipeline_id": pipeline_id},
    )
    has_default = result_to_dict(default_res) is not None
    make_default = not has_default

    await execute(
        """
        UPDATE youtube_destinations
        SET connected = 1,
            connected_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
            channel_id = :channel_id,
            channel_name = :channel_name,
            channel_avatar_url = COALESCE(:channel_avatar_url, channel_avatar_url),
            account_id = COALESCE(:account_id, account_id),
            is_default = CASE WHEN :make_default = 1 THEN 1 ELSE is_default END,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id = :id
        """,
        {
            "id": destination_id,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "channel_avatar_url": channel_avatar_url,
            "account_id": account_id,
            "make_default": 1 if make_default else 0,
        },
    )
    return await get_destination(destination_id)


async def update_destination_connected(
    destination_id: str, connected: bool, account_id: str | None = None
) -> None:
    await execute(
        "UPDATE youtube_destinations SET connected = :connected, "
        "connected_at = CASE WHEN :connected = 1 THEN strftime('%Y-%m-%dT%H:%M:%SZ', 'now') ELSE connected_at END, "
        "account_id = COALESCE(:account_id, account_id), "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = :id",
        {"id": destination_id, "connected": 1 if connected else 0, "account_id": account_id},
    )


async def set_default_destination(pipeline_id: str, destination_id: str) -> dict[str, Any] | None:
    dest = await get_destination(destination_id)
    if dest is None or dest.get("pipeline_id") != pipeline_id:
        return None

    await execute(
        "UPDATE youtube_destinations SET is_default = 0, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE pipeline_id = :pipeline_id",
        {"pipeline_id": pipeline_id},
    )
    await execute(
        "UPDATE youtube_destinations SET is_default = 1, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = :id AND pipeline_id = :pipeline_id",
        {"id": destination_id, "pipeline_id": pipeline_id},
    )
    return await get_destination(destination_id)


async def toggle_destination_enabled(destination_id: str, enabled: bool) -> dict[str, Any] | None:
    await execute(
        "UPDATE youtube_destinations SET enabled = :enabled, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = :id",
        {"id": destination_id, "enabled": 1 if enabled else 0},
    )
    return await get_destination(destination_id)


async def disconnect_destination(destination_id: str) -> dict[str, Any] | None:
    await execute(
        "UPDATE youtube_destinations "
        "SET connected = 0, is_default = 0, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = :id",
        {"id": destination_id},
    )
    return await get_destination(destination_id)


async def delete_destination(destination_id: str) -> bool:
    await execute("DELETE FROM youtube_destinations WHERE id = :id", {"id": destination_id})
    return True


async def get_default_destination(pipeline_id: str) -> dict[str, Any] | None:
    # 1. Try default, enabled and connected
    res = await execute(
        f"SELECT {_COLUMNS} FROM youtube_destinations "
        "WHERE pipeline_id = :pipeline_id AND is_default = 1 AND enabled = 1 AND connected = 1 "
        "LIMIT 1",
        {"pipeline_id": pipeline_id},
    )
    row = result_to_dict(res)
    if row:
        return to_safe_dict(row)

    # 2. Fallback to any enabled and connected
    res = await execute(
        f"SELECT {_COLUMNS} FROM youtube_destinations "
        "WHERE pipeline_id = :pipeline_id AND enabled = 1 AND connected = 1 "
        "ORDER BY created_at ASC LIMIT 1",
        {"pipeline_id": pipeline_id},
    )
    row = result_to_dict(res)
    return to_safe_dict(row)


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
