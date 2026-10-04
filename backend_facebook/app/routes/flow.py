"""Realtime pipeline flow state (no mocks, Turso-aggregated).

GET /api/facebook/pipelines/{pipeline_id}/flow-state
"""

from __future__ import annotations

from fastapi import APIRouter

from ..db.repositories import destinations, pipelines, publications, reels, scan_runs, sources
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
    elif any_source_error:
        source_status = "error"
    elif any_enabled_source:
        source_status = "done"
    else:
        source_status = "idle"

    if any_scanning:
        inventory_status = "running"
    elif any_failed and inventory == 0:
        inventory_status = "error"
    elif inventory > 0:
        inventory_status = "done"
    else:
        inventory_status = "idle"

    yt_destinations = await destinations.list_destinations(pipeline_id)
    if any(
        d.get("connected") and d.get("enabled", True) and d.get("channel_id")
        for d in yt_destinations
    ):
        youtube_destination_status = "done"
    else:
        youtube_destination_status = "idle"

    pub_counts = await publications.status_counts_for_pipeline(pipeline_id)
    if pub_counts.get("processing", 0) > 0:
        publisher_status = "running"
    elif pub_counts.get("failed", 0) > 0:
        publisher_status = "error"
    elif pub_counts.get("published", 0) > 0:
        publisher_status = "done"
    else:
        publisher_status = "idle"

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
            "ai_metadata": "not_configured",
            "scheduler": "not_configured",
            "publisher": publisher_status,
            "youtube_destination": youtube_destination_status,
        },
    }


@router.get("/pipelines/{pipeline_id}/flow-state")
async def get_flow_state(pipeline_id: str) -> dict:
    state = await build_flow_state(pipeline_id)
    if state is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found")
    return state
