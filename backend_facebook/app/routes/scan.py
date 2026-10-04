"""Initial inventory scan endpoints (Task 4).

Provider: RapidAPI (JSON). No HTML scraping, no browser, no downloads.

POST /api/facebook/sources/{source_id}/scan queues a scan run and returns
early; the provider fetch executes as a FastAPI BackgroundTask (in-process,
single instance). No scheduler.
"""

from __future__ import annotations

import logging
import uuid

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from ..auth import require_admin
from ..config import settings
from ..db.repositories import reels, scan_runs, sources
from ..services.facebook_rapidapi import (
    END_OF_RESULTS,
    SAFETY_LIMIT,
    FacebookRapidApiClient,
    RapidApiConfig,
    RapidApiError,
)

logger = logging.getLogger("backend-facebook.scan")

router = APIRouter(prefix="/api/facebook", tags=["facebook-scan"])


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
    }


def _client_from_settings() -> FacebookRapidApiClient:
    keys = [k for k in (settings.RAPIDAPI_KEY, settings.RAPIDAPI_KEY_FALLBACK) if k]
    if not keys:
        raise RapidApiError("RAPIDAPI_AUTH_ERROR", "RAPIDAPI_KEY is not configured.")
    if not settings.FACEBOOK_RAPIDAPI_BASE_URL or not settings.FACEBOOK_RAPIDAPI_HOST:
        raise RapidApiError("RAPIDAPI_AUTH_ERROR", "RapidAPI host/base URL is not configured.")
    return FacebookRapidApiClient(
        RapidApiConfig(
            base_url=settings.FACEBOOK_RAPIDAPI_BASE_URL,
            host=settings.FACEBOOK_RAPIDAPI_HOST,
            api_keys=keys,
            timeout=settings.FACEBOOK_RAPIDAPI_TIMEOUT,
            max_pages=settings.FACEBOOK_RAPIDAPI_MAX_PAGES,
            max_reels=settings.FACEBOOK_RAPIDAPI_MAX_REELS,
        )
    )


def _page_url_for(source: dict) -> str:
    # /page/details resolves the page URL (NOT the /reels/ tab URL) into reels_page_id.
    return f"https://www.facebook.com/{source['page_id']}/"


async def _persist_reel(source_id: str, reel: dict) -> str:
    """Insert one normalized reel. Returns INSERTED / ALREADY_EXISTS / SKIPPED."""
    reel_db_id = f"{source_id}_{reel['reel_id']}"
    try:
        state, _ = await reels.insert_reel_if_new(
            reel_db_id=reel_db_id,
            source_id=source_id,
            reel_id=reel["reel_id"],
            reel_url=reel.get("reel_url"),
            caption=reel.get("caption"),
            thumbnail_url=reel.get("thumbnail_url"),
            source_published_at=reel.get("source_published_at"),
        )
    except Exception as exc:
        logger.warning("insert reel %s failed: %s", reel.get("reel_id"), exc)
        return "SKIPPED"
    return state


async def run_initial_scan(
    scan_run_id: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """Background worker: page Page ID -> RapidAPI -> Turso inventory."""
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
            stop_reason="RAPIDAPI_RESPONSE_INVALID",
        )
        return
    if not source.get("enabled", True):
        await scan_runs.complete_scan_run(
            scan_run_id, status="failed", error="Source is disabled",
            stop_reason="RAPIDAPI_RESPONSE_INVALID",
        )
        return

    await scan_runs.mark_running(scan_run_id)
    discovered = inserted = existing = 0
    pages = 0
    stop_reason = END_OF_RESULTS
    error: str | None = None

    try:
        client = _client_from_settings()
        reels_page_id = await client.resolve_reels_page_id(
            _page_url_for(source), transport=transport
        )
        pages += 1  # resolve request counts toward safety budget

        cursor: str | None = None
        seen_cursors: set[str] = set()
        seen_ids: set[str] = set()
        complete = False

        while True:
            if pages >= client.config.max_pages or len(seen_ids) >= client.config.max_reels:
                stop_reason = SAFETY_LIMIT
                break
            page = await client.list_reels(
                source["page_id"], cursor=cursor, transport=transport,
                reels_page_id=reels_page_id,
            )
            pages += 1

            chunk = max(1, settings.FACEBOOK_SCAN_WRITE_CHUNK)
            for i in range(0, len(page.items), chunk):
                for reel in page.items[i : i + chunk]:
                    if reel["reel_id"] in seen_ids:
                        continue
                    seen_ids.add(reel["reel_id"])
                    discovered += 1
                    state = await _persist_reel(source["id"], reel)
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

            if not page.has_more:
                complete = True
                stop_reason = END_OF_RESULTS
                break
            if page.next_cursor in seen_cursors:
                stop_reason = SAFETY_LIMIT
                break
            if page.next_cursor:
                seen_cursors.add(page.next_cursor)
            if not page.items:
                stop_reason = END_OF_RESULTS
                break
            cursor = page.next_cursor

        total = await reels.count_reels(source["id"])
        if complete:
            final_status, error = "completed", None
        elif discovered > 0:
            final_status, error = "partial", None
        else:
            final_status = "failed"
            error = "Provider returned no reels."
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
    except RapidApiError as exc:
        logger.warning("scan %s provider error %s", scan_run_id, exc.code)
        try:
            total = await reels.count_reels(source["id"])
        except Exception:
            total = 0
        if discovered > 0:
            final_status, error = "partial", None
            stop = exc.code
        else:
            final_status, error = "failed", str(exc) or exc.code
            stop = exc.code
        await scan_runs.complete_scan_run(
            scan_run_id,
            discovered_count=discovered,
            inserted_count=inserted,
            existing_count=existing,
            status=final_status,
            crawl_complete=False,
            stop_reason=stop,
            error=error,
        )
        try:
            await sources.record_scan_finished(
                source["id"], status=final_status, error=error,
                discovered_total=total, crawl_complete=False,
            )
        except Exception:
            logger.exception("failed to record scan failure on source")
    except Exception as exc:  # persisted state must never stay running
        logger.exception("scan %s crashed", scan_run_id)
        safe_error = str(exc)[:500] or "Scan crashed"
        try:
            total = await reels.count_reels(source["id"])
        except Exception:
            total = 0
        await scan_runs.complete_scan_run(
            scan_run_id,
            discovered_count=discovered,
            inserted_count=inserted,
            existing_count=existing,
            status="failed",
            crawl_complete=False,
            stop_reason="RAPIDAPI_UPSTREAM_ERROR",
            error=safe_error,
        )
        try:
            await sources.record_scan_finished(
                source["id"], status="failed", error=safe_error,
                discovered_total=total, crawl_complete=False,
            )
        except Exception:
            logger.exception("failed to record scan failure on source")


@router.post("/sources/{source_id}/scan", status_code=status.HTTP_202_ACCEPTED)
async def start_scan(
    source_id: str,
    background: BackgroundTasks,
    _: None = Depends(require_admin),
) -> dict:
    source = await sources.get_source(source_id)
    if source is None:
        raise _err(404, "SOURCE_NOT_FOUND", "Source not found")
    if not source.get("enabled", True):
        raise _err(400, "SOURCE_DISABLED", "Source is disabled")

    active = await scan_runs.get_active_scan_run(source_id)
    if active is not None:
        raise _err(409, "SCAN_ALREADY_RUNNING", "A scan is already queued or running for this source")

    scan_run_id = f"scan_{uuid.uuid4().hex[:12]}"
    await scan_runs.create_scan_run(scan_run_id=scan_run_id, source_id=source_id, status="queued")
    background.add_task(run_initial_scan, scan_run_id)
    return {"scan_run_id": scan_run_id, "source_id": source_id, "status": "queued"}


@router.get("/scan-runs/{scan_run_id}")
async def get_scan_status(scan_run_id: str) -> dict:
    run = await scan_runs.get_scan_run(scan_run_id)
    if run is None:
        raise _err(404, "SCAN_RUN_NOT_FOUND", "Scan run not found")
    return _scan_response(run)


@router.get("/sources/{source_id}/scan-runs")
async def list_source_scans(source_id: str) -> list[dict]:
    source = await sources.get_source(source_id)
    if source is None:
        raise _err(404, "SOURCE_NOT_FOUND", "Source not found")
    rows = await scan_runs.list_scan_runs(source_id)
    return [_scan_response(r) for r in rows]
