from typing import Any

from ...db.client import execute, result_to_dict, result_to_dicts


async def get_state(key: str) -> str | None:
    res = await execute(
        "SELECT value FROM system_state WHERE key = :key",
        {"key": key},
    )
    return res.rows[0][0] if res.rows else None


async def set_state(key: str, value: str) -> None:
    await execute(
        """
        INSERT INTO system_state (key, value)
        VALUES (:key, :value)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        """,
        {"key": key, "value": value},
    )


async def get_json(key: str, default: Any = None) -> Any:
    import json

    raw = await get_state(key)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


async def set_json(key: str, value: Any) -> None:
    import json

    await set_state(key, json.dumps(value))
