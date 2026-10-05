"""Realtime pipeline flow state (no mocks, Turso-aggregated).

GET /api/facebook/pipelines/{pipeline_id}/flow-state
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter
from zoneinfo import ZoneInfo

from ..db.repositories import destinations, pipelines, publications, reels, scan_runs, schedules, sources
from .facebook import _err

router = APIRouter(prefix="/api/facebook", tags=["facebook-flow"])


async def build_flow_state(pipeline_id: str) -> dict | None:
    """Aggregate Turso into flow state. None when pipeline is missing."""
    pipeline = await pipelines.get_pipeline(pipeline_id)
    if pipeline is None:
        return None

    fb_sources = await sources.list_sources(pipeline_id)
    stats = await reels.inventory_stats(pipeline_id)
    inventory = stats["total"]

    latest_runs = []
    for src in fb_sources:
        run = await scan_runs.latest_scan_run(src["id"])
        if run is not None:
            latest_runs.append(run)

    any_scanning = any(r["status"] in ("queued", "running") for r in latest_runs)
    any_failed = any(r["status"] == "failed" for r in latest_runs)
    any_enabled_source = any(s.get("enabled", True) for s in fb_sources)
    any_source_error = any(
        (s.get("last_scan_status") == "failed" and s.get("last_scan_error")) for s in fb_sources
    )

    if not fb_sources:
        source_status = "idle"
        source_detail = "no sources"
    elif any_source_error:
        source_status = "error"
        source_detail = "Source error"
    elif any_enabled_source:
        source_status = "ready"
        source_detail = f"{len(fb_sources)} sources"
    else:
        source_status = "idle"
        source_detail = "no enabled sources"

    if any_scanning:
        inventory_status = "running"
        inventory_detail = f"{stats.get('processing', 0)} scanning, {inventory} total"
    elif any_failed and inventory == 0:
        inventory_status = "error"
        inventory_detail = "Scan failed, no inventory"
    elif inventory > 0:
        inventory_status = "ready"
        inventory_detail = f"{inventory} videos"
    else:
        inventory_status = "idle"
        inventory_detail = "no videos"

    yt_destinations = await destinations.list_destinations(pipeline_id)
    connected_dest = [
        d for d in yt_destinations
        if d.get("connected") and d.get("enabled", True) and d.get("channel_id")
    ]
    if connected_dest:
        youtube_destination_status = "ready"
        youtube_destination_detail = f"{len(connected_dest)} connected"
    else:
        youtube_destination_status = "idle"
        youtube_destination_detail = "no connected destination"

    pub_counts = await publications.status_counts_for_pipeline(pipeline_id)
    processing = pub_counts.get("processing", 0)
    failed = pub_counts.get("failed", 0)
    published = pub_counts.get("published", 0)
    scheduled = pub_counts.get("scheduled", 0)

    if processing > 0:
        publisher_status = "running"
        publisher_detail = f"{processing} uploading"
    elif failed > 0:
        # Historical failures must not pin the step red forever: error only
        # when failures accompany live work (queued/processing jobs). Healed
        # history surfaces as ready with a note; rows stay visible under
        # Publications with retry. Never delete history to fake green.
        from ..db.repositories import publish_queue as publish_queue_repo

        live_queue = await publish_queue_repo.get_pipeline_queue_stats(pipeline_id)
        live_work = live_queue.get("queued", 0) + live_queue.get("processing", 0)
        if live_work > 0:
            publisher_status = "error"
            publisher_detail = f"{failed} failed"
        else:
            publisher_status = "ready"
            publisher_detail = f"{failed} failed history"
    elif scheduled > 0:
        publisher_status = "ready"
        publisher_detail = f"{scheduled} scheduled"
    elif published > 0:
        publisher_status = "done"
        publisher_detail = f"{published} published"
    else:
        publisher_status = "idle"
        publisher_detail = "no publications"

    from ..db.repositories import ai_metadata as ai_metadata_repo
    from ..config import settings as app_settings

    from ..db.repositories import ai_settings as ai_settings_repo

    pipeline_ai_settings = await ai_settings_repo.get_settings(pipeline_id)
    ai_configured = bool(
        app_settings.TOOLNET_AI_ENABLED
        and app_settings.TOOLNET_BASE_URL
        and app_settings.TOOLNET_API_KEY
        and app_settings.TOOLNET_MODEL
        and pipeline_ai_settings.get("enabled", True)
    )
    ai_stats = await ai_metadata_repo.pipeline_stats(pipeline_id)
    pending = ai_stats.get("pending", 0)
    generated = ai_stats.get("generated", 0)
    failed = ai_stats.get("failed", 0)
    total = ai_stats.get("total_reels", 0)
    ai_processing = stats.get("ai_processing", 0)

    if not ai_configured:
        ai_metadata_status = "not_configured"
        ai_metadata_detail = "AI not configured"
    elif ai_processing > 0:
        ai_metadata_status = "running"
        ai_metadata_detail = f"Đang xử lý · {generated} generated / {pending} pending"
    elif pending > 0 and generated == 0:
        ai_metadata_status = "ready"
        ai_metadata_detail = f"{pending} pending"
    elif pending > 0 and generated > 0:
        ai_metadata_status = "partial"
        ai_metadata_detail = f"{generated} generated, {pending} pending"
    elif failed > 0 and generated == 0:
        ai_metadata_status = "error"
        ai_metadata_detail = f"{failed} failed"
    elif generated > 0 and pending == 0:
        ai_metadata_status = "done"
        ai_metadata_detail = f"{generated} generated"
    else:
        ai_metadata_status = "idle"
        ai_metadata_detail = "no reels"

    schedule = await schedules.get_schedule(pipeline_id)
    if schedule is None or not schedule.get("enabled"):
        scheduler_status = "not_configured"
        scheduler_detail = "Scheduler not configured"
    else:
        utc_now = datetime.now(timezone.utc)
        tz = ZoneInfo(schedule.get("timezone") or "Asia/Ho_Chi_Minh")
        now_local = utc_now.astimezone(tz)
        date_iso = now_local.date().isoformat()
        batch = await schedules.get_batch_for_pipeline_date(pipeline_id, date_iso)
        if batch and batch.get("status") in ("queued", "running"):
            # Only show "running" if there's actual work (planned_count > 0)
            planned = batch.get('planned_count', 0)
            uploaded = batch.get('uploaded_count', 0)
            if planned > 0:
                scheduler_status = "running"
                scheduler_detail = f"Running · {uploaded}/{planned} videos"
            else:
                # Batch exists but no work - show as idle/waiting
                scheduler_status = "idle"
                scheduler_detail = "No work for today"
        elif batch and batch.get("status") == "failed":
            scheduler_status = "error"
            scheduler_detail = f"Failed: {batch.get('last_error', 'unknown')}"
        elif batch and batch.get("status") == "completed":
            scheduler_status = "done"
            scheduler_detail = f"Completed · {batch.get('uploaded_count', 0)} videos"
        elif batch and batch.get("status") == "no_work":
            scheduler_status = "idle"
            scheduler_detail = "No new inventory"
        else:
            # No batch today - show next batch time
            scheduler_status = "waiting"
            batch_time = schedule.get("batch_time") or "06:00"
            batch_hour, batch_minute = map(int, batch_time.split(":"))
            candidate = now_local.replace(hour=batch_hour, minute=batch_minute, second=0, microsecond=0)
            if candidate <= now_local:
                candidate = candidate + timedelta(days=1)
            next_batch_local = candidate.strftime("%H:%M")
            scheduler_detail = f"Waiting · next batch {next_batch_local}"

    return {
        "pipeline_id": pipeline_id,
        "live": bool(pipeline.get("enabled", True)),
        "sources": len(fb_sources),
        "inventory": inventory,
        "queued": stats["queued"],
        "processing": stats["processing"],
        "failed": stats["failed"],
        "steps": {
            "source": source_status,
            "inventory": inventory_status,
            "ai_metadata": ai_metadata_status,
            "scheduler": scheduler_status,
            "publisher": publisher_status,
            "youtube_destination": youtube_destination_status,
        },
        "details": {
            "source": source_detail,
            "inventory": inventory_detail,
            "ai_metadata": ai_metadata_detail,
            "scheduler": scheduler_detail,
            "publisher": publisher_detail,
            "youtube_destination": youtube_destination_detail,
        },
        "active_stage": _compute_active_stage(
            source_status,
            inventory_status,
            ai_metadata_status,
            scheduler_status,
            publisher_status,
            youtube_destination_status,
        ),
        "active_edges": _compute_active_edges(
            source_status,
            inventory_status,
            ai_metadata_status,
            scheduler_status,
            publisher_status,
            youtube_destination_status,
        ),
    }


@router.get("/pipelines/{pipeline_id}/flow-state")
async def get_flow_state(pipeline_id: str) -> dict:
    state = await build_flow_state(pipeline_id)
    if state is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found")
    return state


def _compute_active_stage(
    source_status: str,
    inventory_status: str,
    ai_metadata_status: str,
    scheduler_status: str,
    publisher_status: str,
    youtube_destination_status: str,
) -> str | None:
    """Determine which stage is currently active (doing work right now).
    
    Only stages with 'running' status are considered active.
    """
    # Check in pipeline order
    stages = [
        ("source", source_status),
        ("inventory", inventory_status),
        ("ai_metadata", ai_metadata_status),
        ("scheduler", scheduler_status),
        ("publisher", publisher_status),
        ("youtube_destination", youtube_destination_status),
    ]
    
    for name, status in stages:
        if status == "running":
            return name
    
    return None


def _compute_active_edges(
    source_status: str,
    inventory_status: str,
    ai_metadata_status: str,
    scheduler_status: str,
    publisher_status: str,
    youtube_destination_status: str,
) -> list[str]:
    """Determine which edges should animate based on active runtime work.
    
    An edge animates when:
    - Source node is 'running' (work happening at source)
    - Destination node is 'running' (work happening at destination)
    
    Only the edge INTO the running node animates.
    """
    edges = []
    
    stages = [
        ("source", source_status),
        ("inventory", inventory_status),
        ("ai_metadata", ai_metadata_status),
        ("scheduler", scheduler_status),
        ("publisher", publisher_status),
        ("youtube_destination", youtube_destination_status),
    ]
    
    # Edge names correspond to transition from previous to current
    edge_names = [
        None,  # source has no incoming edge
        "source->inventory",
        "inventory->ai_metadata",
        "ai_metadata->scheduler",
        "scheduler->publisher",
        "publisher->youtube_destination",
    ]
    
    for i, (name, status) in enumerate(stages):
        if status == "running" and i > 0:
            edges.append(edge_names[i])
    
    return edges
