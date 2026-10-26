import json
import secrets
from typing import Any

from ...db.client import execute, result_to_dict, result_to_dicts

_SCHEDULE_COLS = (
    "id, pipeline_id, timezone, enabled, max_daily_publish, batch_time, "
    "active_days, weekend_priority, video_order, min_interval_minutes, "
    "created_at, updated_at"
)


def _hydrate_schedule(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    # Parse active_days if json string
    if "active_days" in row and isinstance(row["active_days"], str):
        try:
            row["active_days"] = json.loads(row["active_days"])
        except Exception:
            row["active_days"] = [0, 1, 2, 3, 4, 5, 6]
    elif "active_days" not in row or row["active_days"] is None:
        row["active_days"] = [0, 1, 2, 3, 4, 5, 6]

    if "weekend_priority" not in row or row["weekend_priority"] is None:
        row["weekend_priority"] = 0
    if "video_order" not in row or not row["video_order"]:
        row["video_order"] = "newest"
    if "min_interval_minutes" not in row or row["min_interval_minutes"] is None:
        row["min_interval_minutes"] = 60
    return row


async def get_or_create_schedule(
    pipeline_id: str,
    timezone: str = "Asia/Ho_Chi_Minh",
    max_daily: int = 5,
    batch_time: str = "06:00",
) -> dict[str, Any]:
    res = await execute(
        f"SELECT {_SCHEDULE_COLS} FROM tiktok_publish_schedules WHERE pipeline_id = :pid",
        {"pid": pipeline_id},
    )
    if res.rows:
        return _hydrate_schedule(result_to_dict(res))
    schedule_id = f"sch_{secrets.token_hex(8)}"
    await execute(
        "INSERT INTO tiktok_publish_schedules (id, pipeline_id, timezone, max_daily_publish, batch_time, "
        "active_days, weekend_priority, video_order, min_interval_minutes) "
        "VALUES (:id, :pid, :tz, :max, :bt, :ad, :wp, :vo, :mi)",
        {
            "id": schedule_id,
            "pid": pipeline_id,
            "tz": timezone,
            "max": max_daily,
            "bt": batch_time,
            "ad": "[0,1,2,3,4,5,6]",
            "wp": 0,
            "vo": "newest",
            "mi": 60,
        },
    )
    res = await execute(
        f"SELECT {_SCHEDULE_COLS} FROM tiktok_publish_schedules WHERE pipeline_id = :pid",
        {"pid": pipeline_id},
    )
    return _hydrate_schedule(result_to_dict(res))


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
    active_days: list[int] | str | None = None,
    weekend_priority: bool | int | None = None,
    video_order: str | None = None,
    min_interval_minutes: int | None = None,
) -> dict[str, Any]:
    updates: list[str] = ["updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"]
    params: dict[str, Any] = {"pid": pipeline_id}
    if timezone is not None:
        updates.append("timezone = :tz")
        params["tz"] = timezone
    if max_daily is not None:
        updates.append("max_daily_publish = :max")
        params["max"] = max(1, min(10, int(max_daily)))
    if batch_time is not None:
        updates.append("batch_time = :bt")
        params["bt"] = batch_time
    if active_days is not None:
        updates.append("active_days = :ad")
        params["ad"] = json.dumps(active_days) if isinstance(active_days, list) else str(active_days)
    if weekend_priority is not None:
        updates.append("weekend_priority = :wp")
        params["wp"] = 1 if weekend_priority else 0
    if video_order is not None:
        updates.append("video_order = :vo")
        params["vo"] = "oldest" if video_order.lower() == "oldest" else "newest"
    if min_interval_minutes is not None:
        updates.append("min_interval_minutes = :mi")
        params["mi"] = max(5, int(min_interval_minutes))

    await execute(
        f"UPDATE tiktok_publish_schedules SET {', '.join(updates)} WHERE pipeline_id = :pid",
        params,
    )
    return await get_or_create_schedule(pipeline_id)


async def get_by_pipeline(pipeline_id: str) -> dict[str, Any] | None:
    res = await execute(
        f"SELECT {_SCHEDULE_COLS} FROM tiktok_publish_schedules WHERE pipeline_id = :pid",
        {"pid": pipeline_id},
    )
    return _hydrate_schedule(result_to_dict(res))


async def create_batch(
    *,
    batch_id: str,
    pipeline_id: str,
    destination_id: str,
    local_date: str,
    scheduled_batch_time: str,
    planned_count: int = 0,
) -> None:
    await execute(
        """
        INSERT INTO tiktok_scheduler_batches
        (id, pipeline_id, destination_id, local_date, scheduled_batch_time, planned_count, status)
        VALUES (:id, :pipeline_id, :destination_id, :local_date, :scheduled_batch_time, :planned_count, 'queued')
        """,
        {
            "id": batch_id,
            "pipeline_id": pipeline_id,
            "destination_id": destination_id,
            "local_date": local_date,
            "scheduled_batch_time": scheduled_batch_time,
            "planned_count": planned_count,
        },
    )


async def get_batch(pipeline_id: str, destination_id: str, local_date: str) -> dict[str, Any] | None:
    res = await execute(
        "SELECT id, pipeline_id, destination_id, local_date, scheduled_batch_time, "
        "started_at, completed_at, status, planned_count, uploaded_count, failed_count, "
        "last_error, created_at "
        "FROM tiktok_scheduler_batches "
        "WHERE pipeline_id = :pipeline_id AND destination_id = :destination_id AND local_date = :local_date",
        {"pipeline_id": pipeline_id, "destination_id": destination_id, "local_date": local_date},
    )
    return result_to_dict(res)


async def complete_batch(batch_id: str, uploaded_count: int, failed_count: int = 0) -> None:
    await execute(
        """
        UPDATE tiktok_scheduler_batches
        SET status = 'completed', completed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
            uploaded_count = :up, failed_count = :fail
        WHERE id = :id
        """,
        {"id": batch_id, "up": uploaded_count, "fail": failed_count},
    )


async def ensure_slots(schedule_id: str) -> None:
    """Ensure basic slot coverage exists for schedule."""
    existing = await execute(
        "SELECT COUNT(*) FROM tiktok_publish_schedule_slots WHERE schedule_id = :sid AND enabled = 1",
        {"sid": schedule_id},
    )
    if existing.rows and existing.rows[0][0] > 0:
        return
    # Generate default slots across weekdays (06:00, 10:48, 15:36, 20:24, 01:12)
    default_slots = ["06:00", "10:48", "15:36", "20:24", "01:12"]
    for wd in range(7):
        for st in default_slots:
            await upsert_slot(schedule_id, wd, st, enabled=True)


async def list_enabled_slots(schedule_id: str) -> list[tuple[int, str]]:
    res = await execute(
        "SELECT weekday, slot_time FROM tiktok_publish_schedule_slots "
        "WHERE schedule_id = :sid AND enabled = 1 ORDER BY weekday, slot_time",
        {"sid": schedule_id},
    )
    return [(r[0], r[1]) for r in res.rows]


async def upsert_slot(schedule_id: str, weekday: int, slot_time: str, enabled: bool = True) -> None:
    slot_id = f"slot_{secrets.token_hex(8)}"
    await execute(
        """
        INSERT INTO tiktok_publish_schedule_slots (id, schedule_id, weekday, slot_time, enabled)
        VALUES (:id, :sid, :wd, :st, :en)
        ON CONFLICT(schedule_id, weekday, slot_time) DO UPDATE SET
            enabled = excluded.enabled,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        """,
        {"id": slot_id, "sid": schedule_id, "wd": weekday, "st": slot_time, "en": 1 if enabled else 0},
    )


async def sync_weekday_slots(schedule_id: str, weekday: int, active_slot_times: list[str]) -> None:
    """Synchronize slots for a specific weekday.

    Any slot in active_slot_times is enabled (upserted if not exists).
    Any existing enabled slot not in active_slot_times is disabled.
    """
    active_set = set(active_slot_times)
    existing = await list_slots(schedule_id)
    for s in existing:
        if s["weekday"] == weekday and s["slot_time"] not in active_set and s.get("enabled"):
            await set_slot_enabled(schedule_id, weekday, s["slot_time"], False)
    for st in active_slot_times:
        await upsert_slot(schedule_id, weekday, st, enabled=True)


async def set_slot_enabled(schedule_id: str, weekday: int, slot_time: str, enabled: bool) -> None:
    await upsert_slot(schedule_id, weekday, slot_time, enabled=enabled)


async def list_slots(schedule_id: str) -> list[dict[str, Any]]:
    res = await execute(
        "SELECT id, schedule_id, weekday, slot_time, enabled, created_at, updated_at "
        "FROM tiktok_publish_schedule_slots WHERE schedule_id = :sid ORDER BY weekday, slot_time",
        {"sid": schedule_id},
    )
    return result_to_dicts(res)
