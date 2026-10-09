"""Scheduler tick: due pipelines -> reserve one item -> create job (no overlap)."""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone

logger = logging.getLogger("backend-audio.scheduler")


def _today_utc_start(tz_name: str) -> str:
    """Return local midnight formatted as UTC ISO string for accurate daily cap queries."""
    try:
        from zoneinfo import ZoneInfo

        local_tz = ZoneInfo(tz_name)
        local_now = datetime.now(local_tz)
    except Exception:
        local_tz = timezone.utc
        local_now = datetime.now(timezone.utc)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    utc_midnight = local_midnight.astimezone(timezone.utc)
    return utc_midnight.strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_next_slot(valid_slots: list[tuple[int, int]], local_now: datetime,
                   local_tz: timezone) -> datetime:
    today_slots = [
        local_now.replace(hour=h, minute=m, second=0, microsecond=0)
        for h, m in valid_slots
    ]
    upcoming = [s for s in today_slots if s > local_now]
    if upcoming:
        return upcoming[0]
    tomorrow_date = local_now.date() + timedelta(days=1)
    return datetime.combine(
        tomorrow_date,
        time(hour=valid_slots[0][0], minute=valid_slots[0][1]),
        tzinfo=local_tz
    )


def pipeline_due(pipeline_id: str) -> tuple[bool, str]:
    from app.db.client import get_client
    from app.db.repositories import audio as audio_repo
    from app.db.repositories import pipelines as pipe_repo

    pipe = pipe_repo.get_pipeline(pipeline_id)
    if not pipe:
        return False, "pipeline not found"
    if pipe.get("pipeline_type") == "manual":
        return False, "manual pipeline"
    if not pipe.get("enabled"):
        return False, "pipeline disabled"
    if not pipe.get("auto_publish"):
        return False, "pipeline auto_publish disabled"

    sched = audio_repo.get_scheduler_settings(pipeline_id)
    if not sched.get("enabled"):
        return False, "scheduler disabled"
    dest_id = sched.get("destination_id")
    if dest_id:
        dest = audio_repo.get_destination(dest_id)
        if not dest or not dest.get("connected") or not dest.get("enabled"):
            return False, "destination not connected"
    else:
        connected = [d for d in audio_repo.list_destinations(pipeline_id)
                     if d.get("connected") and d.get("enabled")]
        if not connected:
            return False, "no connected destination"

    # Requirement 3: Resource check before job creation
    backgrounds = [a for a in audio_repo.list_assets(pipeline_id, "background")
                   if a.get("enabled")]
    if not backgrounds:
        return False, "NO_BACKGROUND"

    now_utc = datetime.now(timezone.utc)
    now_utc_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    if sched.get("next_run_at") and sched["next_run_at"] > now_utc_str:
        return False, "waiting for next_run_at"

    tz_name = sched.get("timezone") or "Asia/Ho_Chi_Minh"
    day_start = _today_utc_start(tz_name)
    client = get_client()
    row = client.execute(
        "SELECT COUNT(*) AS n FROM audio_publications WHERE pipeline_id = ? "
        "AND published_at >= ?", (pipeline_id, day_start)).fetchone()
    try:
        published_today = int(row["n"]) if row and row.get("n") is not None else 0
    except (ValueError, TypeError):
        published_today = 0
    max_videos = int(sched.get("max_videos_per_day") or 3)
    if published_today >= max_videos:
        return False, "daily cap reached"

    # Requirement 2: Daily times evaluation
    try:
        from zoneinfo import ZoneInfo

        local_tz = ZoneInfo(tz_name)
        local_now = datetime.now(local_tz)
    except Exception:
        local_tz = timezone.utc
        local_now = now_utc

    raw_times = sched.get("daily_times") or []
    valid_slots: list[tuple[int, int]] = []
    for t in raw_times:
        try:
            parts = str(t).strip().split(":")
            if len(parts) >= 2:
                h, m = int(parts[0]), int(parts[1])
                if 0 <= h <= 23 and 0 <= m <= 59:
                    valid_slots.append((h, m))
        except Exception:
            continue
    valid_slots.sort()

    if valid_slots:
        slot_window = timedelta(minutes=30)
        today_slots = [
            local_now.replace(hour=h, minute=m, second=0, microsecond=0)
            for h, m in valid_slots
        ]
        last_run_local = None
        if sched.get("last_run_at"):
            try:
                last_run_local = datetime.strptime(
                    sched["last_run_at"], "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc).astimezone(local_tz)
            except Exception:
                pass

        active_slot = None
        for slot in today_slots:
            if slot <= local_now < slot + slot_window:
                if last_run_local and last_run_local >= slot:
                    continue
                active_slot = slot
                break

        if active_slot is None:
            next_slot = _get_next_slot(valid_slots, local_now, local_tz)
            next_utc_str = next_slot.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if sched.get("next_run_at") != next_utc_str:
                audio_repo.set_scheduler_run_marks(pipeline_id, next_run_at=next_utc_str)
            return False, "waiting for next_run_at"

    if sched.get("last_run_at"):
        gap = timedelta(minutes=int(sched.get("min_gap_minutes") or 120))
        last = datetime.strptime(sched["last_run_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
        if now_utc - last < gap:
            return False, "min gap not elapsed"
    return True, "due"


def tick_pipeline(pipeline_id: str) -> dict:
    """One tick: if due, reserve next item (with source rotation) and queue a job."""
    from app.db.repositories import audio as audio_repo
    from app.db.repositories import jobs as jobs_repo
    from app.db.repositories import now_iso
    from app.db.repositories import sources as src_repo

    due, reason = pipeline_due(pipeline_id)
    if not due:
        return {"pipeline_id": pipeline_id, "due": False, "reason": reason}
    sched = audio_repo.get_scheduler_settings(pipeline_id)
    item = None
    if sched.get("rotate_sources"):
        for src in src_repo.list_sources(pipeline_id):
            if not src.get("enabled"):
                continue
            item = src_repo.reserve_next_available(
                pipeline_id, sched.get("order_mode") or "oldest_first",
                source_id=src["id"])
            if item:
                break
    if item is None:
        item = src_repo.reserve_next_available(
            pipeline_id, sched.get("order_mode") or "oldest_first")
    if item is None:
        return {"pipeline_id": pipeline_id, "due": True,
                "reason": "queue empty", "job_id": None}
    existing = get_client_for_jobs().execute(
        "SELECT id FROM audio_processing_jobs WHERE inventory_id = ? "
        "AND status IN ('queued','running')", (item["id"],)).fetchone()
    if existing:
        return {"pipeline_id": pipeline_id, "due": True,
                "reason": "already queued", "job_id": existing["id"]}
    job = jobs_repo.create_job(pipeline_id, inventory_id=item["id"], mode="auto")

    # Compute next run mark if daily_times configured
    tz_name = sched.get("timezone") or "Asia/Ho_Chi_Minh"
    try:
        from zoneinfo import ZoneInfo

        local_tz = ZoneInfo(tz_name)
        local_now = datetime.now(local_tz)
    except Exception:
        local_tz = timezone.utc
        local_now = datetime.now(timezone.utc)
    raw_times = sched.get("daily_times") or []
    valid_slots: list[tuple[int, int]] = []
    for t in raw_times:
        try:
            parts = str(t).strip().split(":")
            if len(parts) >= 2:
                valid_slots.append((int(parts[0]), int(parts[1])))
        except Exception:
            continue
    valid_slots.sort()
    next_mark = None
    if valid_slots:
        next_slot = _get_next_slot(valid_slots, local_now, local_tz)
        next_mark = next_slot.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    audio_repo.set_scheduler_run_marks(pipeline_id, last_run_at=now_iso(),
                                       next_run_at=next_mark)
    return {"pipeline_id": pipeline_id, "due": True, "reason": "queued",
            "job_id": job["id"], "inventory_id": item["id"]}


def get_client_for_jobs():
    from app.db.client import get_client

    return get_client()
