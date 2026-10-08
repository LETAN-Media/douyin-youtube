"""Per-episode segment rendering.

Every segment leaves this module with IDENTICAL output properties so the
final concat can use stream copy:

- video: H.264, canvas WxH, 30fps, yuv420p
- audio: AAC, 44100 Hz, stereo
- container: MP4

Canvas comes from the pipeline template when enabled, else a 1280x720
default. Content is fitted (aspect-preserved), never stretched.
"""

import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger("backend-drama-segment")

DEFAULT_CANVAS = (1280, 720)
DEFAULT_FPS = 30
DEFAULT_AR = 44100


class SegmentError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def standard_canvas(template: dict[str, Any] | None) -> tuple[int, int, int, int, int, int]:
    """(canvas_w, canvas_h, content_x, content_y, content_w, content_h)."""
    if template:
        cw = int(template.get("canvas_width") or DEFAULT_CANVAS[0])
        ch = int(template.get("canvas_height") or DEFAULT_CANVAS[1])
        x = int(template.get("content_x") or 0)
        y = int(template.get("content_y") or 0)
        w = int(template.get("content_width") or cw)
        h = int(template.get("content_height") or ch)
    else:
        cw, ch, x, y, w, h = (*DEFAULT_CANVAS, 0, 0, *DEFAULT_CANVAS)
    if min(cw, ch, w, h) <= 0 or x < 0 or y < 0:
        raise SegmentError("SEGMENT_RENDER_FAILED", "Invalid segment geometry.")
    return cw, ch, x, y, w, h


def render_episode_segment(
    source: Path,
    output: Path,
    *,
    template_frame: Path | None = None,
    canvas: tuple[int, int, int, int, int, int] | None = None,
    timeout: int = 1800,
) -> Path:
    """Normalize one episode (+ optional template overlay) to the standard
    segment profile. One invocation per episode; deterministic output."""
    if canvas is None:
        cw, ch, x, y, w, h = (*DEFAULT_CANVAS, 0, 0, *DEFAULT_CANVAS)
    else:
        cw, ch, x, y, w, h = canvas
    output.parent.mkdir(parents=True, exist_ok=True)
    base = (
        f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={DEFAULT_FPS},"
        f"pad={cw}:{ch}:{x}:{y}:black,setsar=1"
    )
    if template_frame is not None:
        vf = (
            f"{base}[v0];"
            f"[1:v]scale={cw}:{ch}[frame];"
            f"[v0][frame]overlay=0:0,setsar=1[v]"
        )
        inputs = ["-i", str(source), "-i", str(template_frame)]
        maps = ["-map", "[v]", "-map", "0:a?"]
    else:
        vf = base + "[v]"
        inputs = ["-i", str(source)]
        maps = ["-map", "[v]", "-map", "0:a?"]
    cmd = [
        "ffmpeg", "-v", "error", "-y", *inputs,
        "-filter_complex", vf, *maps,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", str(DEFAULT_AR), "-ac", "2",
        str(output),
    ]
    try:
        subprocess.run(cmd, check=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise SegmentError("SEGMENT_RENDER_TIMEOUT", "Episode render timed out.") from exc
    except subprocess.CalledProcessError as exc:
        raise SegmentError("SEGMENT_RENDER_FAILED", "ffmpeg episode render failed.") from exc
    if not output.exists() or output.stat().st_size <= 0:
        raise SegmentError("SEGMENT_RENDER_FAILED", "Episode render produced no output.")
    return output
