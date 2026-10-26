from ...db.client import execute, result_to_dict, result_to_dicts


async def is_paused(pipeline_id: str) -> tuple[bool, str | None]:
    res = await execute(
        "SELECT paused_until, reason FROM tiktok_quota_pauses WHERE pipeline_id = :pid",
        {"pid": pipeline_id},
    )
    if not res.rows:
        return False, None
    row = result_to_dict(res)
    paused_until = row.get("paused_until") or ""
    if _is_future(paused_until):
        return True, row.get("reason")
    return False, row.get("reason")


async def set_pause(pipeline_id: str, pause_minutes: int, reason: str | None = None) -> None:
    await execute(
        """
        INSERT INTO tiktok_quota_pauses (pipeline_id, paused_until, reason)
        VALUES (:pid, :until, :reason)
        ON CONFLICT(pipeline_id) DO UPDATE SET
            paused_until = excluded.paused_until,
            reason = COALESCE(excluded.reason, tiktok_quota_pauses.reason),
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        """,
        {"pid": pipeline_id, "until": _future_iso(pause_minutes), "reason": reason},
    )


async def clear_pause(pipeline_id: str) -> None:
    await execute("DELETE FROM tiktok_quota_pauses WHERE pipeline_id = :pid", {"pid": pipeline_id})


def _is_future(ts: str) -> bool:
    import time as _time
    try:
        return _time.time() < _time.mktime(_time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, TypeError):
        return False


def _future_iso(minutes: int) -> str:
    import time as _time
    return _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(_time.time() + minutes * 60))
