"""YouTube Shorts eligibility verification and format classification using ffprobe.

Rules applied:
- Duration: at most 180 seconds (3 minutes)
- Aspect ratio: square (1:1) or vertical (9:16), i.e. width <= height

Publishing modes supported:
- 'shorts': Only publish if eligible for Shorts; ineligible files are rejected with error note.
- 'video': Publish as regular video regardless of dimensions.
- 'both': Automatically publish under the matching format (Shorts if eligible, otherwise regular video).
  Each source video is only published once under its matching format.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger("backend-tiktok.shorts")

SHORTS_MAX_SECONDS = 180


class ShortsCheckError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _ffprobe_path() -> str:
    found = shutil.which("ffprobe")
    if not found:
        raise ShortsCheckError(
            "SHORTS_CHECK_UNAVAILABLE",
            "ffprobe is not installed; cannot verify video dimensions and duration.",
        )
    return found


def probe_file(path: Path | str) -> dict[str, Any]:
    """Inspect video file metadata via ffprobe."""
    target_path = Path(path)
    if not target_path.exists():
        raise ShortsCheckError("FILE_NOT_FOUND", f"Video file not found: {target_path}")

    try:
        res = subprocess.run(
            [
                _ffprobe_path(),
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(target_path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
    except ShortsCheckError:
        raise
    except subprocess.TimeoutExpired as exc:
        raise ShortsCheckError("SHORTS_CHECK_UNAVAILABLE", "ffprobe timed out probing media.") from exc
    except Exception as exc:
        raise ShortsCheckError("SHORTS_CHECK_UNAVAILABLE", f"ffprobe execution failed: {exc}") from exc

    try:
        data = json.loads(res.stdout or "{}")
    except ValueError as exc:
        raise ShortsCheckError("SHORTS_CHECK_UNAVAILABLE", "ffprobe returned invalid JSON output.") from exc

    duration = 0.0
    try:
        duration = float((data.get("format") or {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0

    width = 0
    height = 0
    for stream in data.get("streams", []) or []:
        if stream.get("codec_type") == "video":
            try:
                width = int(stream.get("width") or 0)
                height = int(stream.get("height") or 0)
            except (TypeError, ValueError):
                width = height = 0
            break

    return {
        "duration": duration,
        "width": width,
        "height": height,
        "is_vertical": height > width and width > 0,
        "is_square": height == width and width > 0,
        "is_landscape": width > height and height > 0,
    }


def check_shorts_eligibility(path: Path | str) -> tuple[bool, str, dict[str, Any]]:
    """Determine whether video file satisfies YouTube Shorts criteria.

    Returns:
        (is_eligible: bool, note: str, probe_info: dict)
    """
    info = probe_file(path)
    duration = info["duration"]
    width, height = info["width"], info["height"]

    orientation = (
        "vertical (dọc)"
        if height > width
        else "square (vuông)"
        if height == width and width > 0
        else "landscape (ngang)"
        if width > 0
        else "unknown"
    )

    reasons: list[str] = []
    if duration <= 0:
        reasons.append("Không thể xác định thời lượng video")
    elif duration > SHORTS_MAX_SECONDS:
        reasons.append(f"Thời lượng {duration:.1f}s vượt quá giới hạn Shorts ({SHORTS_MAX_SECONDS}s)")

    if width <= 0 or height <= 0:
        reasons.append("Không thể xác định độ phân giải video")
    elif width > height:
        reasons.append(f"Video định dạng ngang ({width}x{height}), YouTube Shorts yêu cầu dọc hoặc vuông")

    if reasons:
        note = f"{int(duration)}s · {width}x{height} {orientation} · Không đủ điều kiện Shorts: " + "; ".join(reasons)
        return False, note, info

    note = f"{int(duration)}s · {width}x{height} {orientation} · Đủ điều kiện Shorts"
    return True, note, info


def classify_upload_format(requested_mode: str, path: Path | str) -> tuple[str, bool, str, dict[str, Any]]:
    """Classify video for upload according to pipeline's youtube_upload_mode setting.

    Returns:
        (target_format: 'shorts' | 'video', can_proceed: bool, note: str, probe_info: dict)
    """
    normalized_mode = (requested_mode or "shorts").lower().strip()

    if normalized_mode == "video":
        info = probe_file(path)
        return "video", True, "Đăng dưới định dạng Regular Video theo cấu hình Pipeline", info

    eligible, note, info = check_shorts_eligibility(path)

    if normalized_mode == "shorts":
        if not eligible:
            return "shorts", False, note, info
        return "shorts", True, note, info

    # normalized_mode == "both"
    if eligible:
        return "shorts", True, f"Tự động xuất bản dưới dạng Shorts: {note}", info
    return "video", True, f"Tự động xuất bản dưới dạng Regular Video (không thỏa Shorts): {note}", info
