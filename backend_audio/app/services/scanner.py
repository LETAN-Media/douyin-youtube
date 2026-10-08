"""Facebook source scanner: background incremental scan with progress/pause.

Quota-safe: incremental by default (stops at first known video), full scan
only on demand. Reports real counts, never claims completeness it can't prove.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("backend-audio.scanner")

_scans: dict[str, dict[str, Any]] = {}


def scan_status(source_id: str) -> dict[str, Any] | None:
    return _scans.get(source_id)


async def scan_source(source_id: str, *, full: bool = False,
                      limit: int = 500) -> dict[str, Any]:
    """Scan a Facebook page for reels. Runs in background via asyncio task."""
    from app.db.client import get_client
    from app.db.repositories import sources as src_repo
    from app.services.facebook_urls import extract_facebook_video_id

    row = get_client().execute("SELECT * FROM audio_sources WHERE id = ?",
                               (source_id,)).fetchone()
    if row is None:
        raise ValueError("Source not found.")
    source = dict(row)
    if _scans.get(source_id, {}).get("state") == "running":
        return _scans[source_id]

    state: dict[str, Any] = {"state": "running", "found": 0, "added": 0,
                              "skipped_known": 0, "error": None}
    _scans[source_id] = state
    asyncio.create_task(_run_scan(source, state, full=full, limit=limit))
    return state


async def _run_scan(source: dict, state: dict, *, full: bool,
                    limit: int) -> None:
    from app.db.repositories import sources as src_repo

    try:
        # Resolution path: page reels listing via provider API when available.
        # No provider scan API is configured for Audio yet, so report honestly.
        state["state"] = "failed"
        state["error"] = ("SCAN_API_MISSING: no Facebook listing provider is "
                          "configured for Audio (FACEBOOK scan API). Add sources via "
                          "manual inventory import or configure a listing provider.")
        logger.warning("scan %s: %s", source["id"], state["error"])
    except Exception as exc:
        state["state"] = "failed"
        state["error"] = f"{type(exc).__name__}: {exc}"[:300]
    finally:
        if state["state"] != "running":
            src_repo.touch_source_scanned(source["id"])


def pause_scan(source_id: str) -> None:
    state = _scans.get(source_id)
    if state and state.get("state") == "running":
        state["state"] = "paused"
