"""Per-pipeline YouTube quota pause state.

A quota/rate-limit rejection pauses only the affected pipeline. Queued jobs
for that pipeline remain durable and are retried after the pause expires;
other pipelines continue normally.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ..client import get_client


def _now_utc(now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def pause_pipeline(
    pipeline_id: str,
    *,
    minutes: int,
    reason: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Pause one pipeline for at least `minutes`, extending any active pause."""
    client = get_client()
    current = _now_utc(now)
    until = current + timedelta(minutes=max(1, int(minutes)))
    existing = await get_active_pause(pipeline_id, now=current)
    if existing is not None:
        existing_until = datetime.fromisoformat(
            str(existing["paused_until"]).replace("Z", "+00:00")
        )
        if existing_until > until:
            until = existing_until
    params = {
        "pipeline_id": pipeline_id,
        "paused_until": _iso(until),
        "reason": (reason or "")[:500] or None,
    }
    if existing is None:
        await client.execute(
            "INSERT INTO facebook_quota_pauses (pipeline_id, paused_until, reason) "
            "VALUES (:pipeline_id, :paused_until, :reason) "
            "ON CONFLICT(pipeline_id) DO UPDATE SET "
            "paused_until = excluded.paused_until, reason = excluded.reason, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')",
            params,
        )
    else:
        await client.execute(
            "UPDATE facebook_quota_pauses SET paused_until = :paused_until, "
            "reason = :reason, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
            "WHERE pipeline_id = :pipeline_id",
            params,
        )
    return {
        "pipeline_id": pipeline_id,
        "paused_until": _iso(until),
        "reason": params["reason"],
    }


async def get_active_pause(
    pipeline_id: str, *, now: datetime | None = None
) -> dict[str, Any] | None:
    client = get_client()
    current = _now_utc(now)
    rows = await client.execute(
        "SELECT pipeline_id, paused_until, reason, updated_at "
        "FROM facebook_quota_pauses WHERE pipeline_id = :pipeline_id",
        {"pipeline_id": pipeline_id},
    )
    if not rows.rows:
        return None
    row = rows.rows[0]
    try:
        until = datetime.fromisoformat(str(row[1]).replace("Z", "+00:00"))
    except Exception:
        return None
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    if until <= current:
        return None
    return {
        "pipeline_id": row[0],
        "paused_until": _iso(until),
        "reason": row[2],
        "updated_at": row[3],
    }


async def clear_pause(pipeline_id: str) -> None:
    client = get_client()
    await client.execute(
        "DELETE FROM facebook_quota_pauses WHERE pipeline_id = :pipeline_id",
        {"pipeline_id": pipeline_id},
    )
