"""Initial inventory scan endpoints using self-hosted API.

Provider: facebook-data-api on VPS (JSON). No HTML scraping, no browser, no downloads.

POST /api/facebook/sources/{source_id}/scan-self-hosted queues a scan run and returns
early; the provider fetch executes as a FastAPI BackgroundTask (in-process,
single instance). No scheduler.
"""

from __future__ import annotations

import logging
import re
import uuid

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from ..auth import require_admin
from ..config import settings
from ..db.repositories import reels, scan_runs, sources
from ..services.facebook_self_hosted import (
    END_OF_RESULTS,
    SAFETY_LIMIT,
    FacebookSelfHostedClient,
    SelfHostedApiConfig,
    SelfHostedApiError,
)

KNOWN_REELS_REACHED = "KNOWN_REELS_REACHED"

SCAN_MODES = ("auto", "full", "incremental")

logger = logging.getLogger("backend-facebook.scan-self-hosted")

router = APIRouter(prefix="/api/facebook", tags=["facebook-scan-self-hosted"])


def _err(status_code: int, error: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": error, "message": message})


def _scan_response(row: dict) -> dict:
    return {
        "id": row["id"],
        "source_id": row["source_id"],
        "status": row["status"],
        "discovered_count": row.get("discovered_count", 0),
        "inserted_count": row.get("inserted_count", 0),
        "existing_count": row.get("existing_count", 0),
        "crawl_complete": row.get("crawl_complete", False),
        "stop_reason": row.get("stop_reason"),
        "error": row.get("error"),
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
        "scan_mode": row.get("scan_mode"),
    }


def _resolve_mode(requested: str, source: dict) -> str:
    if requested == "incremental":
        return "incremental"
    if requested in ("full", "initial"):
        return "initial"
    return "incremental" if source.get("initial_scan_completed") else "initial"


def _client_from_settings() -> FacebookSelfHostedClient:
    if not settings.SELFHOSTED_API_KEY:
        raise SelfHostedApiError("SELFHOSTED_AUTH_ERROR", "SELFHOSTED_API_KEY is not configured.")
    if not settings.SELFHOSTED_API_BASE_URL:
        raise SelfHostedApiError("SELFHOSTED_AUTH_ERROR", "SELFHOSTED_API_BASE_URL is not configured.")
    return FacebookSelfHostedClient(
        SelfHostedApiConfig(
            base_url=settings.SELFHOSTED_API_BASE_URL,
            api_key=settings.SELFHOSTED_API_KEY,
            timeout=settings.SELFHOSTED_API_TIMEOUT,
            max_reels=settings.SELFHOSTED_API_MAX_REELS,
        )
    )


def _page_url_for(source: dict) -> str:
    return f"https://www.facebook.com/{source['page_id']}/reels/"


def _extract_reel_id(reel_url: str) -> str | None:
    """Extract reel ID from URL like https://www.facebook.com/reel/29117076781219786"""
    match = re.search(r'/reel/(\d+)', reel_url)
    return match.group(1) if match else None


async def _persist_reel(source_id: str, reel_url: str) -> str:
    """Insert one reel URL. Returns INSERTED / ALREADY_EXISTS / SKIPPED."""
    reel_id = _extract_reel_id(reel_url)
    if not reel_id:
        logger.warning("failed to extract reel_id from %s", reel_url)
        return "SKIPPED"
    
    reel_db_id = f"{source_id}_{reel_id}"
    try:
        state, _ = await reels.insert_reel_if_new(
            reel_db_id=reel_db_id,
            source_id=source_id,
            reel_id=reel_id,
            reel_url=reel_url,
            caption=None,
            thumbnail_url=None,
            source_published_at=None,
        )
    except Exception as exc:
        logger.warning("insert reel %s failed: %s", reel_id, exc)
        return "SKIPPED"
    return state


async def run_self_hosted_scan(
    scan_run_id: str,
    transport: httpx.AsyncBaseTransport | None = None,
    mode: str = "auto",
) -> None:
    """Background worker: page URL -> self-hosted API -> Turso inventory.
    
    Self-hosted API returns all reels in one request (no pagination).
    """
    run = await scan_runs.get_scan_run(scan_run_id)
    if run is None:
        logger.warning("scan run %s not found, skipping", scan_run_id)
        return
    if run["status"] not in ("queued", "running"):
        return

    source = await sources.get_source(run["source_id"])
    if source is None:
        await scan_runs.complete_scan_run(
            scan_run_id, status="failed", error="Source not found",
            stop_reason="SELFHOSTED_RESPONSE_INVALID",
        )
        return
    if not source.get("enabled", True):
        await scan_runs.complete_scan_run(
            scan_run_id, status="failed", error="Source is disabled",
            stop_reason="SELFHOSTED_RESPONSE_INVALID",
        )
        return

    await scan_runs.mark_running(scan_run_id)
    scan_mode = _resolve_mode(mode, source)
    await scan_runs.set_scan_mode(scan_run_id, scan_mode)
    discovered = inserted = existing = 0
    stop_reason = END_OF_RESULTS
    error: str | None = None

    try:
        client = _client_from_settings()
        page_url = _page_url_for(source)
        
        reel_urls = await client.fetch_reels(page_url, transport=transport)
        
        if len(reel_urls) > client.config.max_reels:
            reel_urls = reel_urls[:client.config.max_reels]
            stop_reason = SAFETY_LIMIT
        
        seen_ids: set[str] = set()
        chunk = max(1, settings.FACEBOOK_SCAN_WRITE_CHUNK)
        
        for i in range(0, len(reel_urls), chunk):
            for reel_url in reel_urls[i : i + chunk]:
                reel_id = _extract_reel_id(reel_url)
                if not reel_id or reel_id in seen_ids:
                    continue
                seen_ids.add(reel_id)
                discovered += 1
                state = await _persist_reel(source["id"], reel_url)
                if state == "INSERTED":
                    inserted += 1
                elif state == "ALREADY_EXISTS":
                    existing += 1
            await scan_runs.update_progress(
                scan_run_id,
                discovered_count=discovered,
                inserted_count=inserted,
                existing_count=existing,
            )

        total = await reels.count_reels(source["id"])
        if discovered > 0:
            final_status, error = "completed", None
            complete = True
        else:
            final_status = "failed"
            error = "Provider returned no reels."
            complete = False
        
        await scan_runs.complete_scan_run(
            scan_run_id,
            discovered_count=discovered,
            inserted_count=inserted,
            existing_count=existing,
            status=final_status,
            crawl_complete=complete,
            stop_reason=stop_reason,
            error=error,
        )
        await sources.record_scan_finished(
            source["id"], status=final_status, error=error,
            discovered_total=total, crawl_complete=complete,
        )
    except SelfHostedApiError as exc:
        logger.warning("scan %s provider error %s", scan_run_id, exc.code)
        await scan_runs.complete_scan_run(
            scan_run_id,
            discovered_count=discovered,
            inserted_count=inserted,
            existing_count=existing,
            status="failed",
            error=str(exc),
            stop_reason=exc.code,
        )
        await sources.record_scan_finished(source["id"], status="failed", error=str(exc))
    except Exception as exc:
        logger.exception("scan %s unexpected error", scan_run_id)
        await scan_runs.complete_scan_run(
            scan_run_id,
            discovered_count=discovered,
            inserted_count=inserted,
            existing_count=existing,
            status="failed",
            error=f"Internal error: {type(exc).__name__}",
            stop_reason="SELFHOSTED_UPSTREAM_ERROR",
        )
        await sources.record_scan_finished(
            source["id"], status="failed", error=f"Internal error: {type(exc).__name__}"
        )


@router.post("/sources/{source_id}/scan-self-hosted", response_model=dict)
async def initiate_scan_self_hosted(
    source_id: str,
    background_tasks: BackgroundTasks,
    mode: str = "auto",
    _auth: None = Depends(require_admin),
) -> dict:
    """Queue a self-hosted API scan run for the given source."""
    if mode not in SCAN_MODES:
        raise _err(status.HTTP_400_BAD_REQUEST, "INVALID_MODE", f"Invalid mode: {mode}")

    source = await sources.get_source(source_id)
    if source is None:
        raise _err(status.HTTP_404_NOT_FOUND, "SOURCE_NOT_FOUND", f"Source {source_id} not found")
    if not source.get("enabled", True):
        raise _err(status.HTTP_400_BAD_REQUEST, "SOURCE_DISABLED", "Source is disabled")

    scan_run_id = str(uuid.uuid4())
    await scan_runs.create_scan_run(scan_run_id, source_id)
    background_tasks.add_task(run_self_hosted_scan, scan_run_id, mode=mode)
    row = await scan_runs.get_scan_run(scan_run_id)
    assert row is not None
    return _scan_response(row)


@router.get("/scans/{scan_run_id}", response_model=dict)
async def get_scan_run_status(
    scan_run_id: str,
    _auth: None = Depends(require_admin),
) -> dict:
    """Retrieve the status of a specific scan run."""
    row = await scan_runs.get_scan_run(scan_run_id)
    if row is None:
        raise _err(status.HTTP_404_NOT_FOUND, "SCAN_NOT_FOUND", f"Scan run {scan_run_id} not found")
    return _scan_response(row)
