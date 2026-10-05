from typing import Any

from ..client import get_client

_COLUMNS = (
    "id, pipeline_id, channel_id, channel_name, visibility, enabled, "
    "connected, connected_at, created_at, updated_at"
)


def _row_to_dict(r: Any) -> dict[str, Any]:
    return {
        "id": r[0],
        "pipeline_id": r[1],
        "channel_id": r[2],
        "channel_name": r[3],
        "visibility": r[4],
        "enabled": bool(r[5]),
        "connected": bool(r[6]) if len(r) > 6 and r[6] is not None else False,
        "connected_at": r[7] if len(r) > 7 else None,
        "created_at": r[8] if len(r) > 8 else None,
        "updated_at": r[9] if len(r) > 9 else None,
    }


def to_safe_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Public API shape. Never includes credentials or secrets."""
    return {
        "id": row["id"],
        "pipeline_id": row["pipeline_id"],
        "channel_id": row.get("channel_id"),
        "channel_name": row.get("channel_name"),
        "visibility": row.get("visibility", "public"),
        "enabled": row.get("enabled", True),
        "connected": row.get("connected", False),
    }


async def create_destination(
    *,
    destination_id: str,
    pipeline_id: str,
    channel_id: str | None = None,
    channel_name: str | None = None,
    visibility: str = "public",
    enabled: bool = True,
) -> dict[str, Any]:
    """Create an unconnected destination. Channel identity is filled by OAuth."""
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
    created = await get_destination(destination_id)
    if created is not None:
        return created
    return {
        "id": destination_id,
        "pipeline_id": pipeline_id,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "visibility": visibility,
        "enabled": enabled,
        "connected": False,
        "connected_at": None,
    }


async def get_destination(destination_id: str) -> dict[str, Any] | None:
    client = get_client()
    try:
        rows = await client.execute(
            f"SELECT {_COLUMNS} FROM youtube_destinations WHERE id = :id",
            {"id": destination_id},
        )
    except Exception:
        rows = await client.execute(
            "SELECT id, pipeline_id, channel_id, channel_name, visibility, enabled, created_at, updated_at FROM youtube_destinations WHERE id = :id",
            {"id": destination_id},
        )
    if not rows.rows:
        return None
    return _row_to_dict(rows.rows[0])


async def list_destinations(pipeline_id: str) -> list[dict[str, Any]]:
    client = get_client()
    try:
        rows = await client.execute(
            f"SELECT {_COLUMNS} FROM youtube_destinations WHERE pipeline_id = :pipeline_id",
            {"pipeline_id": pipeline_id},
        )
    except Exception:
        rows = await client.execute(
            "SELECT id, pipeline_id, channel_id, channel_name, visibility, enabled, created_at, updated_at FROM youtube_destinations WHERE pipeline_id = :pipeline_id",
            {"pipeline_id": pipeline_id},
        )
    return [_row_to_dict(r) for r in rows.rows]


async def set_connected(
    destination_id: str, *, channel_id: str, channel_name: str
) -> None:
    client = get_client()
    await client.execute(
        "UPDATE youtube_destinations SET channel_id = :channel_id, channel_name = :channel_name, "
        "connected = 1, connected_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {"channel_id": channel_id, "channel_name": channel_name, "id": destination_id},
    )


async def list_connected_with_pipelines() -> list[dict[str, Any]]:
    """All logged-in (connected) YouTube destinations across pipelines.

    Safe fields only — never credentials. Ordered by channel name.
    """
    client = get_client()
    try:
        rows = await client.execute(
            "SELECT d.id, d.pipeline_id, d.channel_id, d.channel_name, "
            "d.visibility, d.enabled, d.connected, p.name "
            "FROM youtube_destinations d "
            "LEFT JOIN facebook_pipelines p ON p.id = d.pipeline_id "
            "WHERE d.connected = 1 "
            "ORDER BY d.channel_name, d.id"
        )
    except Exception:
        rows = await client.execute(
            "SELECT id, pipeline_id, channel_id, channel_name, visibility, "
            "enabled, connected, NULL FROM youtube_destinations "
            "WHERE connected = 1 ORDER BY channel_name, id"
        )
    out = []
    for r in rows.rows or []:
        out.append({
            "id": r[0],
            "pipeline_id": r[1],
            "pipeline_name": r[7],
            "channel_id": r[2],
            "channel_name": r[3],
            "visibility": r[4] or "public",
            "enabled": bool(r[5]),
            "connected": True,
        })
    return out


async def disconnect_destination(destination_id: str) -> dict[str, Any] | None:
    """Safe disconnect: keep the row (history still resolves channel names),
    clear the connection. Credentials and OAuth states are deleted by the
    caller (youtube_auth helpers). Returns the updated row or None."""
    client = get_client()
    res = await client.execute(
        "UPDATE youtube_destinations SET connected = 0, enabled = 0, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {"id": destination_id},
    )
    if (res.rows_affected or 0) == 0:
        # Row may already be disconnected; still return it if it exists.
        existing = await get_destination(destination_id)
        if existing is None:
            return None
        return existing
    updated = await get_destination(destination_id)
    assert updated is not None
    return updated
