"""Weekly publish schedules + slots + scheduler runs (Task 9)."""

from __future__ import annotations

import re
import uuid
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..client import get_client

WEEKDAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_NAME_TO_WEEKDAY = {name: idx for idx, name in enumerate(WEEKDAY_NAMES)}

DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"
DEFAULT_MAX_DAILY = 5
DEFAULT_BATCH_TIME = "06:00"

DEFAULT_SLOTS: dict[int, list[str]] = {
    0: ["11:30", "14:30", "18:30", "20:30", "22:30"],
    1: ["11:30", "14:30", "18:30", "20:30", "22:30"],
    2: ["11:30", "14:30", "18:30", "20:30", "22:30"],
    3: ["11:30", "14:30", "18:30", "20:30", "22:30"],
    4: ["11:30", "14:30", "18:30", "20:30", "22:30"],
    5: ["09:30", "11:30", "15:00", "19:30", "21:30"],
    6: ["09:00", "11:00", "15:30", "19:00", "21:00"],
}

_SLOT_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def validate_timezone(value: str | None) -> str:
    name = (value or "").strip() or DEFAULT_TIMEZONE
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"Invalid timezone: {value!r}.")
    return name


def normalize_slots(slots: dict[Any, Any] | None) -> dict[int, list[str]]:
    """Accept {monday: [...]} or {0: [...]}. Enforce <=5 unique valid sorted HH:MM per day."""
    if slots is None:
        return {day: list(times) for day, times in DEFAULT_SLOTS.items()}
    normalized: dict[int, list[str]] = {}
    for key, times in slots.items():
        if isinstance(key, int):
            day = key
        else:
            day = _NAME_TO_WEEKDAY.get(str(key).strip().lower(), -1)
        if day < 0 or day > 6:
            raise ValueError(f"Invalid weekday: {key!r}.")
        if not isinstance(times, list):
            raise ValueError(f"Slots for {key!r} must be a list.")
        cleaned = sorted({str(t).strip() for t in times if str(t).strip()})
        for t in cleaned:
            if not _SLOT_RE.match(t):
                raise ValueError(f"Invalid slot time: {t!r} (expected HH:MM).")
        if len(cleaned) > 5:
            raise ValueError(f"Too many slots for {key!r}: max 5 per day.")
        normalized[day] = cleaned
    return normalized


def _row_to_schedule(r: Any, slots: dict[int, list[str]]) -> dict[str, Any]:
    return {
        "id": r[0],
        "pipeline_id": r[1],
        "timezone": r[2],
        "enabled": bool(r[3]),
        "max_daily_publish": r[4],
        "batch_time": r[5] if len(r) > 5 else None,
        "created_at": r[6] if len(r) > 6 else None,
        "updated_at": r[7] if len(r) > 7 else None,
        "slots": slots,
    }


async def get_schedule(pipeline_id: str) -> dict[str, Any] | None:
    client = get_client()
    rows = await client.execute(
        "SELECT id, pipeline_id, timezone, enabled, max_daily_publish, batch_time, created_at, updated_at "
        "FROM facebook_publish_schedules WHERE pipeline_id = :pipeline_id",
        {"pipeline_id": pipeline_id},
    )
    if not rows.rows:
        return None
    schedule_id = rows.rows[0][0]
    slot_rows = await client.execute(
        "SELECT weekday, slot_time FROM facebook_publish_schedule_slots "
        "WHERE schedule_id = :sid AND enabled = 1 ORDER BY weekday, slot_time",
        {"sid": schedule_id},
    )
    slots: dict[int, list[str]] = {}
    for r in slot_rows.rows or []:
        slots.setdefault(int(r[0]), []).append(r[1])
    return _row_to_schedule(rows.rows[0], slots)


async def list_enabled_schedules() -> list[dict[str, Any]]:
    """All enabled schedules with slots. One query for schedules, one for slots."""
    client = get_client()
    rows = await client.execute(
        "SELECT id, pipeline_id, timezone, enabled, max_daily_publish, batch_time, created_at, updated_at "
        "FROM facebook_publish_schedules WHERE enabled = 1"
    )
    if not rows.rows:
        return []
    ids = [r[0] for r in rows.rows]
    placeholders = ",".join(f":sid{i}" for i in range(len(ids)))
    slot_rows = await client.execute(
        "SELECT schedule_id, weekday, slot_time FROM facebook_publish_schedule_slots "
        f"WHERE schedule_id IN ({placeholders}) AND enabled = 1 ORDER BY weekday, slot_time",
        {f"sid{i}": sid for i, sid in enumerate(ids)},
    )
    by_schedule: dict[str, dict[int, list[str]]] = {}
    for r in slot_rows.rows or []:
        by_schedule.setdefault(r[0], {}).setdefault(int(r[1]), []).append(r[2])
    return [_row_to_schedule(r, by_schedule.get(r[0], {})) for r in rows.rows]


async def upsert_schedule(
    pipeline_id: str,
    *,
    enabled: bool,
    timezone: str | None,
    max_daily_publish: int,
    slots: dict[Any, Any] | None,
    batch_time: str | None = None,
) -> dict[str, Any]:
    tz = validate_timezone(timezone)
    normalized = normalize_slots(slots)
    if max_daily_publish < 1 or max_daily_publish > 5:
        raise ValueError("max_daily_publish must be between 1 and 5.")
    bt = (batch_time or "").strip() or DEFAULT_BATCH_TIME
    if not _SLOT_RE.match(bt):
        raise ValueError(f"Invalid batch_time: {bt!r} (expected HH:MM).")
    client = get_client()
    existing = await get_schedule(pipeline_id)
    if existing is None:
        schedule_id = f"sch_{uuid.uuid4().hex[:12]}"
        await client.execute(
            "INSERT INTO facebook_publish_schedules "
            "(id, pipeline_id, timezone, enabled, max_daily_publish, batch_time) "
            "VALUES (:id, :pipeline_id, :tz, :enabled, :max_daily, :batch_time)",
            {"id": schedule_id, "pipeline_id": pipeline_id, "tz": tz,
             "enabled": 1 if enabled else 0, "max_daily": max_daily_publish,
             "batch_time": bt},
        )
    else:
        schedule_id = existing["id"]
        await client.execute(
            "UPDATE facebook_publish_schedules SET timezone = :tz, enabled = :enabled, "
            "max_daily_publish = :max_daily, batch_time = :batch_time, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
            {"tz": tz, "enabled": 1 if enabled else 0, "max_daily": max_daily_publish,
             "batch_time": bt, "id": schedule_id},
        )
        await client.execute(
            "DELETE FROM facebook_publish_schedule_slots WHERE schedule_id = :sid",
            {"sid": schedule_id},
        )
    for day in range(7):
        for slot_time in normalized.get(day, []):
            await client.execute(
                "INSERT INTO facebook_publish_schedule_slots (id, schedule_id, weekday, slot_time, enabled) "
                "VALUES (:id, :sid, :day, :slot, 1)",
                {"id": f"slot_{uuid.uuid4().hex[:12]}", "sid": schedule_id,
                 "day": day, "slot": slot_time},
            )
    result = await get_schedule(pipeline_id)
    assert result is not None
    return result


async def claim_slot_run(
    *, run_id: str, pipeline_id: str, destination_id: str, scheduled_for: str
) -> bool:
    """Atomic exactly-once claim. True only for the first claimer."""
    client = get_client()
    try:
        await client.execute(
            "INSERT INTO facebook_scheduler_runs "
            "(id, pipeline_id, destination_id, scheduled_for, status) "
            "VALUES (:id, :pipeline_id, :destination_id, :scheduled_for, 'queued')",
            {"id": run_id, "pipeline_id": pipeline_id,
             "destination_id": destination_id, "scheduled_for": scheduled_for},
        )
    except Exception:
        return False
    return True


async def get_slot_run(pipeline_id: str, destination_id: str, scheduled_for: str) -> dict[str, Any] | None:
    client = get_client()
    rows = await client.execute(
        "SELECT id, pipeline_id, destination_id, scheduled_for, started_at, completed_at, "
        "status, publication_id, reel_db_id, error, created_at "
        "FROM facebook_scheduler_runs "
        "WHERE pipeline_id = :pipeline_id AND destination_id = :destination_id "
        "AND scheduled_for = :scheduled_for",
        {"pipeline_id": pipeline_id, "destination_id": destination_id, "scheduled_for": scheduled_for},
    )
    if not rows.rows:
        return None
    r = rows.rows[0]
    return {
        "id": r[0], "pipeline_id": r[1], "destination_id": r[2], "scheduled_for": r[3],
        "started_at": r[4], "completed_at": r[5], "status": r[6],
        "publication_id": r[7], "reel_db_id": r[8], "error": r[9], "created_at": r[10],
    }


async def mark_run_started(run_id: str) -> None:
    client = get_client()
    await client.execute(
        "UPDATE facebook_scheduler_runs SET status = 'running', "
        "started_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {"id": run_id},
    )


async def mark_run_finished(
    run_id: str, *, status: str, publication_id: str | None = None,
    reel_db_id: str | None = None, error: str | None = None,
) -> None:
    client = get_client()
    await client.execute(
        "UPDATE facebook_scheduler_runs SET status = :status, publication_id = :publication_id, "
        "reel_db_id = :reel_db_id, error = :error, "
        "completed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {"status": status, "publication_id": publication_id, "reel_db_id": reel_db_id,
         "error": (error or "")[:500] if error else None, "id": run_id},
    )


async def count_published_between(pipeline_id: str, start_utc_iso: str, end_utc_iso: str) -> int:
    """Published publications in [start, end). Failed/skipped/processing excluded."""
    client = get_client()
    rows = await client.execute(
        "SELECT COUNT(*) FROM publications p WHERE p.destination_id IN "
        "(SELECT id FROM youtube_destinations WHERE pipeline_id = :pipeline_id) "
        "AND p.status = 'published' AND p.published_at >= :start AND p.published_at < :end",
        {"pipeline_id": pipeline_id, "start": start_utc_iso, "end": end_utc_iso},
    )
    return rows.rows[0][0] if rows.rows else 0


async def has_new_inventory(pipeline_id: str) -> bool:
    """LIMIT 1 existence check — never scans full inventory per tick."""
    client = get_client()
    rows = await client.execute(
        "SELECT 1 FROM facebook_reels r WHERE r.source_id IN "
        "(SELECT id FROM facebook_sources WHERE pipeline_id = :pipeline_id) "
        "AND r.status = 'new' LIMIT 1",
        {"pipeline_id": pipeline_id},
    )
    return bool(rows.rows)


async def latest_run(pipeline_id: str) -> dict[str, Any] | None:
    """Most recent scheduler run for flow-state mapping."""
    client = get_client()
    rows = await client.execute(
        "SELECT id, pipeline_id, destination_id, scheduled_for, started_at, completed_at, "
        "status, publication_id, reel_db_id, error, created_at "
        "FROM facebook_scheduler_runs WHERE pipeline_id = :pipeline_id "
        "ORDER BY created_at DESC, id DESC LIMIT 1",
        {"pipeline_id": pipeline_id},
    )
    if not rows.rows:
        return None
    r = rows.rows[0]
    return {
        "id": r[0], "pipeline_id": r[1], "destination_id": r[2], "scheduled_for": r[3],
        "started_at": r[4], "completed_at": r[5], "status": r[6],
        "publication_id": r[7], "reel_db_id": r[8], "error": r[9], "created_at": r[10],
    }


async def create_batch(
    *,
    batch_id: str,
    pipeline_id: str,
    destination_id: str,
    local_date: str,
    scheduled_batch_time: str,
) -> None:
    """Atomically claim a daily batch. Raises on duplicate."""
    client = get_client()
    await client.execute(
        """
        INSERT INTO facebook_scheduler_batches
        (id, pipeline_id, destination_id, local_date, scheduled_batch_time, status)
        VALUES (:id, :pipeline_id, :destination_id, :local_date, :scheduled_batch_time, 'queued')
        """,
        {
            "id": batch_id,
            "pipeline_id": pipeline_id,
            "destination_id": destination_id,
            "local_date": local_date,
            "scheduled_batch_time": scheduled_batch_time,
        },
    )


async def get_batch(pipeline_id: str, destination_id: str, local_date: str) -> dict[str, Any] | None:
    client = get_client()
    rows = await client.execute(
        "SELECT id, pipeline_id, destination_id, local_date, scheduled_batch_time, "
        "started_at, completed_at, status, planned_count, uploaded_count, failed_count, "
        "last_error, created_at "
        "FROM facebook_scheduler_batches "
        "WHERE pipeline_id = :pipeline_id AND destination_id = :destination_id AND local_date = :local_date",
        {"pipeline_id": pipeline_id, "destination_id": destination_id, "local_date": local_date},
    )
    if not rows.rows:
        return None
    r = rows.rows[0]
    return {
        "id": r[0], "pipeline_id": r[1], "destination_id": r[2], "local_date": r[3],
        "scheduled_batch_time": r[4], "started_at": r[5], "completed_at": r[6],
        "status": r[7], "planned_count": r[8], "uploaded_count": r[9], "failed_count": r[10],
        "last_error": r[11], "created_at": r[12],
    }


async def get_batch_for_pipeline_date(pipeline_id: str, local_date: str) -> dict[str, Any] | None:
    """Return the most recent batch for a pipeline on a given local date, regardless of destination."""
    client = get_client()
    rows = await client.execute(
        "SELECT id, pipeline_id, destination_id, local_date, scheduled_batch_time, "
        "started_at, completed_at, status, planned_count, uploaded_count, failed_count, "
        "last_error, created_at "
        "FROM facebook_scheduler_batches "
        "WHERE pipeline_id = :pipeline_id AND local_date = :local_date "
        "ORDER BY created_at DESC, id DESC LIMIT 1",
        {"pipeline_id": pipeline_id, "local_date": local_date},
    )
    if not rows.rows:
        return None
    r = rows.rows[0]
    return {
        "id": r[0], "pipeline_id": r[1], "destination_id": r[2], "local_date": r[3],
        "scheduled_batch_time": r[4], "started_at": r[5], "completed_at": r[6],
        "status": r[7], "planned_count": r[8], "uploaded_count": r[9], "failed_count": r[10],
        "last_error": r[11], "created_at": r[12],
    }


async def mark_batch_started(batch_id: str) -> None:
    client = get_client()
    await client.execute(
        "UPDATE facebook_scheduler_batches SET status = 'running', "
        "started_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = :id",
        {"id": batch_id},
    )


async def mark_batch_finished(
    batch_id: str,
    status: str,
    *,
    planned_count: int | None = None,
    uploaded_count: int | None = None,
    failed_count: int | None = None,
    error: str | None = None,
) -> None:
    client = get_client()
    sets = ["status = :status", "completed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"]
    params: dict[str, Any] = {"id": batch_id, "status": status}
    if planned_count is not None:
        sets.append("planned_count = :planned_count")
        params["planned_count"] = planned_count
    if uploaded_count is not None:
        sets.append("uploaded_count = :uploaded_count")
        params["uploaded_count"] = uploaded_count
    if failed_count is not None:
        sets.append("failed_count = :failed_count")
        params["failed_count"] = failed_count
    if error is not None:
        sets.append("last_error = :error")
        params["error"] = (error or "")[:500]
    await client.execute(
        f"UPDATE facebook_scheduler_batches SET {', '.join(sets)} WHERE id = :id",
        params,
    )


async def update_batch_planned(batch_id: str, planned: int) -> None:
    client = get_client()
    await client.execute(
        "UPDATE facebook_scheduler_batches SET planned_count = :planned WHERE id = :id",
        {"planned": planned, "id": batch_id},
    )
