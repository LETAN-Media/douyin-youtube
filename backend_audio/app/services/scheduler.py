"""Scheduler tick: due pipelines -> reserve one item -> create job (no overlap)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("backend-audio.scheduler")


def _today_str(tz_name: str) -> str:
    try:
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo(tz_name))
    except Exception:
        now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d")


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
        if not dest or not dest.get("connected"):
            return False, "destination not connected"
    else:
        connected = [d for d in audio_repo.list_destinations(pipeline_id)
                     if d.get("connected") and d.get("enabled")]
        if not connected:
            return False, "no connected destination"
    now = datetime.now(timezone.utc)
    if sched.get("next_run_at") and sched["next_run_at"] > now.strftime(
            "%Y-%m-%dT%H:%M:%SZ"):
        return False, "waiting for next_run_at"
    client = get_client()
    day_start = _today_str(sched.get("timezone") or "Asia/Ho_Chi_Minh") + "T00:00:00Z"
    published_today = client.execute(
        "SELECT COUNT(*) AS n FROM audio_publications WHERE pipeline_id = ? "
        "AND published_at >= ?", (pipeline_id, day_start)).fetchone()["n"]
    if published_today >= int(sched.get("max_videos_per_day") or 3):
        return False, "daily cap reached"
    if sched.get("last_run_at"):
        gap = timedelta(minutes=int(sched.get("min_gap_minutes") or 120))
        last = datetime.strptime(sched["last_run_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
        if now - last < gap:
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
        from app.db.client import get_client

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
    audio_repo.set_scheduler_run_marks(pipeline_id, last_run_at=now_iso())
    return {"pipeline_id": pipeline_id, "due": True, "reason": "queued",
            "job_id": job["id"], "inventory_id": item["id"]}


def get_client_for_jobs():
    from app.db.client import get_client

    return get_client()
