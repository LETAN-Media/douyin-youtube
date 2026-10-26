from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks

from ..dependencies import require_admin
from ..db.repositories import pipelines, scan_runs, sources
from ..services.tiktok_scan import scan_source

router = APIRouter(prefix="/api/tiktok/scan", tags=["scan"])


@router.post("/{source_id}/run", dependencies=[Depends(require_admin)])
async def run_scan(source_id: str, background: BackgroundTasks):
    source = await sources.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    import secrets as _secrets

    scan_run_id = f"scan_{_secrets.token_hex(8)}"
    await scan_runs.create_scan_run(scan_run_id, source_id, scan_mode="manual")
    background.add_task(_do_scan, source_id, scan_run_id)
    return {"scan_run_id": scan_run_id, "status": "started", "source_id": source_id}


@router.post("/{source_id}/run_sync", dependencies=[Depends(require_admin)])
async def run_scan_sync(source_id: str):
    """Synchronous scan — waits for completion."""
    source = await sources.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    import secrets as _secrets

    scan_run_id = f"scan_{_secrets.token_hex(8)}"
    await scan_runs.create_scan_run(scan_run_id, source_id, scan_mode="manual")
    stats = await scan_source(source_id, scan_run_id, scan_mode="manual")
    if source.get("pipeline_id"):
        from ..services.dashboard_cache import invalidate_pipeline
        invalidate_pipeline(source["pipeline_id"])
    return {"scan_run_id": scan_run_id, "stats": stats}


@router.get("/run/{scan_run_id}", dependencies=[Depends(require_admin)])
async def get_scan_run(scan_run_id: str):
    row = await scan_runs.get_scan_run(scan_run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Scan run not found")
    return row


@router.get("/source/{source_id}/runs", dependencies=[Depends(require_admin)])
async def list_scan_runs(source_id: str, limit: int = 20):
    from ..db.client import execute, result_to_dicts

    res = await execute(
        "SELECT id, source_id, started_at, completed_at, discovered_count, "
        "inserted_count, existing_count, crawl_complete, status, error, scan_mode "
        "FROM tiktok_scan_runs WHERE source_id = :sid ORDER BY started_at DESC LIMIT :limit",
        {"sid": source_id, "limit": limit},
    )
    return result_to_dicts(res)


async def _do_scan(source_id: str, scan_run_id: str):
    try:
        await scan_source(source_id, scan_run_id, scan_mode="manual")
        source = await sources.get_source(source_id)
        if source and source.get("pipeline_id"):
            from ..services.dashboard_cache import invalidate_pipeline
            invalidate_pipeline(source["pipeline_id"])
    except Exception as exc:
        import logging

        logging.getLogger("backend-tiktok").error("scan %s failed: %s", scan_run_id, exc)
