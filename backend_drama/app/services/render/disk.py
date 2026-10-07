"""Temporary disk safety for render jobs.

A 60-episode series must never fill the disk. Pre-flight estimates worst
case usage (sources + merged + final ≈ 3x content bytes) and refuses with
a typed error when space is short. Designed so object-storage spillover
can replace the local-workdir branch later.
"""

import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger("backend-drama-disk")

# Assumed average bitrate when unknown (bits/s), headroom factor covering
# sources + merged + final coexisting, and a post-job reserve.
ASSUMED_BPS = 2_500_000
SIZE_FACTOR = 3.0
MIN_ESTIMATE_BYTES = 100 * 1024 * 1024
RESERVE_BYTES = 256 * 1024 * 1024
DEFAULT_EPISODE_SECONDS = 180.0


class DiskError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def disk_free_bytes(path: Path) -> int:
    try:
        return shutil.disk_usage(path if path.exists() else path.parent).free
    except Exception as exc:
        raise DiskError("DISK_UNREADABLE", f"Cannot read disk space: {exc}") from exc


def estimate_job_bytes(episodes: list[dict[str, Any]]) -> int:
    """Worst-case temp bytes for downloading + merging + final."""
    total_seconds = 0.0
    for ep in episodes:
        try:
            duration = float(ep.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0.0
        total_seconds += duration if duration > 0 else DEFAULT_EPISODE_SECONDS
    estimate = int(total_seconds * (ASSUMED_BPS / 8) * SIZE_FACTOR)
    return max(estimate, MIN_ESTIMATE_BYTES if episodes else 0)


def check_temp_space(workdir: Path, required_bytes: int,
                     reserve_bytes: int = RESERVE_BYTES) -> int:
    """Raise INSUFFICIENT_TEMP_STORAGE when unsafe. Returns free bytes."""
    free = disk_free_bytes(workdir)
    if free < required_bytes + reserve_bytes:
        raise DiskError(
            "INSUFFICIENT_TEMP_STORAGE",
            f"Need ~{required_bytes // 1024 // 1024}MB temp + "
            f"{reserve_bytes // 1024 // 1024}MB reserve, "
            f"only {free // 1024 // 1024}MB free at {workdir}.",
        )
    logger.info("disk check %s: free=%dMB required~%dMB", workdir,
                free // 1024 // 1024, required_bytes // 1024 // 1024)
    return free
