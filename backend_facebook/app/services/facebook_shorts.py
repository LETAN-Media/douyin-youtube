"""YouTube Shorts eligibility verification for the actual media file.

Current YouTube Shorts rules applied here:
- duration at most 180 seconds (3 minutes)
- square or vertical aspect (width <= height)

Nothing is trimmed or re-encoded by this module: ineligible files fail
loudly with SHORTS_INELIGIBLE instead of silently losing content. Video
mode skips verification entirely (uploads as-is; note that YouTube itself
may still classify a short vertical file as a Short).

Requires ffprobe (ffmpeg package). Missing binary -> SHORTS_CHECK_UNAVAILABLE.
"""

import json
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("backend-facebook-shorts")

SHORTS_MAX_SECONDS = 180


class ShortsCheckError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _ffprobe_path() -> str:
    found = shutil.which("ffprobe")
    if not found:
        raise ShortsCheckError(
            "SHORTS_CHECK_UNAVAILABLE",
            "ffprobe is not installed; cannot verify Shorts eligibility.",
        )
    return found


def probe_file(path: Path) -> dict:
    """ffprobe -> {duration, width, height}. Raises ShortsCheckError."""
    try:
        res = subprocess.run(
            [_ffprobe_path(), "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, check=True, timeout=60,
        )
    except ShortsCheckError:
        raise
    except subprocess.TimeoutExpired as exc:
        raise ShortsCheckError("SHORTS_CHECK_UNAVAILABLE", "ffprobe timed out.") from exc
    except Exception as exc:
        raise ShortsCheckError("SHORTS_CHECK_UNAVAILABLE", f"ffprobe failed: {exc}") from exc
    try:
        data = json.loads(res.stdout or "{}")
    except ValueError as exc:
        raise ShortsCheckError("SHORTS_CHECK_UNAVAILABLE", "ffprobe returned invalid JSON.") from exc
    duration = 0.0
    try:
        duration = float((data.get("format") or {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    width = height = 0
    for stream in data.get("streams", []) or []:
        if stream.get("codec_type") == "video":
            try:
                width = int(stream.get("width") or 0)
                height = int(stream.get("height") or 0)
            except (TypeError, ValueError):
                width = height = 0
            break
    return {"duration": duration, "width": width, "height": height}


def check_shorts_eligibility(path: Path) -> tuple[bool, str]:
    """Returns (eligible, human-readable note). Never trims or converts."""
    info = probe_file(path)
    duration = info["duration"]
    width, height = info["width"], info["height"]
    orientation = (
        "vertical" if height > width
        else "square" if height == width and width > 0
        else "landscape" if width > 0
        else "unknown"
    )
    reasons: list[str] = []
    if duration <= 0:
        reasons.append("không đọc được thời lượng")
    elif duration > SHORTS_MAX_SECONDS:
        reasons.append(f"dài {duration:.0f}s, vượt quá 180s")
    if width <= 0 or height <= 0:
        reasons.append("không đọc được kích thước")
    elif width > height:
        reasons.append(f"ngang {width}x{height}, cần dọc hoặc vuông")
    if reasons:
        note = f"{int(duration)}s · {width}x{height} {orientation} · không đủ điều kiện: " + "; ".join(reasons)
        return False, note
    note = f"{int(duration)}s · {width}x{height} {orientation} · đủ điều kiện Shorts"
    return True, note
