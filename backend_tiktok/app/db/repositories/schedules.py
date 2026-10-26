import secrets
from typing import Any

from ...db.client import execute, result_to_dict, result_to_dicts


async def get_or_create_schedule(
    pipeline_id: str,
    timezone: str = "Asia/Ho_Chi_Minh",
    max_daily: int = 5,
    batch_time: str = "06:00",
) -> dict[str, Any]:
    res = await execute(
        "SELECT id, pipeline_id, timezone, enabled, max_daily_publish, batch_time, created_at, updated_at "
        "FROM tiktok_publish_schedules WHERE pipeline_id = :pid",
        {"pid": pipeline_id},
    )
    if res.rows:
        return result_to_dict(res)
    schedule_id = f"sch_{secrets.token_hex(8)}"
    await execute(
        "INSERT INTO tiktok_publish_schedules (id, pipeline_id, timezone, max_daily_publish, batch_time) "
        "VALUES (:id, :pid, :tz, :max, :bt)",
        {"id": schedule_id, "pid": pipeline_id, "tz": timezone, "max": max_daily, "bt": batch_time},
    )
    res = await execute(
        "SELECT id, pipeline_id, timezone, enabled, max_daily_publish, batch_time, created_at, updated_at "
        "FROM tiktok_publish_schedules WHERE pipeline_id = :pid",
        {"pid": pipeline_id},
    )
    return result_to_dict(res)


async def set_schedule_enabled(pipeline_id: str, enabled: bool) -> dict[str, Any]:
    await execute(
        "UPDATE tiktok_publish_schedules SET enabled = :enabled, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE pipeline_id = :pid",
        {"pid": pipeline_id, "enabled": 1 if enabled else 0},
    )
    return await get_or_create_schedule(pipeline_id)


async def update_schedule(
    pipeline_id: str,
    timezone: str | None = None,
    max_daily: int | None = None,
    batch_time: str | None = None,
) -> dict[str, Any]:
    updates: list[str] = ["updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"]
    params: dict[str, Any] = {"pid": pipeline_id}
    if timezone is not None:
        updates.append("timezone = :tz")
        params["tz"] = timezone
    if max_daily is not None:
        updates.append("max_daily_publish = :max")
        params["max"] = max_daily
    if batch_time is not None:
        updates.append("batch_time = :bt")
        params["bt"] = batch_time
    await execute(
        f"UPDATE tiktok_publish_schedules SET {', '.join(updates)} WHERE pipeline_id = :pid",
        params,
    )
    return await get_or_create_schedule(pipeline_id)


async def get_by_pipeline(pipeline_id: str) -> dict[str, Any] | None:
    res = await execute(
        "SELECT id, pipeline_id, timezone, enabled, max_daily_publish, batch_time, created_at, updated_at "
        "FROM tiktok_publish_schedules WHERE pipeline_id = :pid",
        {"pid": pipeline_id},
    )
    return result_to_dict(res)


async def ensure_slots(schedule_id: str) -> None:
    """Ensure all 7 weekdays x 24 hours slots exist (default-disabled)."""
    existing = await execute(
        "SELECT DISTINCT weekday, slot_time FROM tiktok_publish_schedule_slots WHERE schedule_id = :sid",
        {"sid": schedule_id},
    )
    have = {(r[0], r[1]) for r in existing.rows}
    new_slots: list[tuple[int, str]] = []
    for weekday in range(7):
        for hour in range(24):
            t = f"{hour:02d}:00"
            if (weekday, t) not in have:
                new_slots.append((weekday, t))
    if not new_slots:
        return
    rows = []
    for i, (wd, t) in enumerate(new_slots):
        rows.append(f"('{schedule_id}', {wd}, '{t}', 0)")
    await execute(
        f"INSERT INTO tiktok_publish_schedule_slots (schedule_id, weekday, slot_time, enabled) "
        f"VALUES {', '.join(rows)}"
    )


async def list_enabled_slots(schedule_id: str) -> list[tuple[int, str]]:
    res = await execute(
        "SELECT weekday, slot_time FROM tiktok_publish_schedule_slots "
        "WHERE schedule_id = :sid AND enabled = 1 ORDER BY weekday, slot_time",
        {"sid": schedule_id},
    )
    return [(r[0], r[1]) for r in res.rows]


async def set_slot_enabled(schedule_id: str, weekday: int, slot_time: str, enabled: bool) -> None:
    await execute(
        "UPDATE tiktok_publish_schedule_slots SET enabled = :enabled, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE schedule_id = :sid AND weekday = :wd AND slot_time = :st",
        {"sid": schedule_id, "wd": weekday, "st": slot_time, "enabled": 1 if enabled else 0},
    )


async def list_slots(schedule_id: str) -> list[dict[str, Any]]:
    res = await execute(
        "SELECT id, schedule_id, weekday, slot_time, enabled, created_at, updated_at "
        "FROM tiktok_publish_schedule_slots WHERE schedule_id = :sid ORDER BY weekday, slot_time",
        {"sid": schedule_id},
    )
    return result_to_dicts(res)
