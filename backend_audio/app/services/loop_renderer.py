"""Loop renderer: background x looped to audio duration + logo overlay, ONE ffmpeg pass."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("backend-audio.render")


class RenderError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def build_loop_video(
    *,
    background: Path,
    audio: Path,
    output: Path,
    duration: float,
    logo: Path | None = None,
    logo_scale: float = 0.12,
    logo_margin: int = 24,
    logo_position: str = "top-right",
    orientation: str = "landscape",
    fps: int = 24,
    threads: int = 2,
    still_image: bool = False,
    preset: str = "veryfast",
    template: Path | None = None,
    template_interval_s: float = 600,
    template_duration_s: float | None = None,
    srt: Path | None = None,
    hardsub: bool = False,
) -> Path:
    """Render final MP4 matching audio duration.

    - Video looped with -stream_loop -1 + -shortest (no black tail, no overrun).
    - Optional fullscreen template overlay at repeating marks
      (enable=between() chain, single pass, main audio kept).
    - Logo overlay in the same filter graph (single pass).
    - Optional hardsub burn-in (subtitles filter, SAME single pass, never a
      second encode). Requires srt when hardsub=True.
    - H.264 + AAC + yuv420p.
    """
    if duration <= 0:
        raise RenderError("BAD_DURATION", "Audio duration must be positive.")
    if hardsub and srt is None:
        raise RenderError("HARDSUB_SRT_MISSING",
                          "hardsub requested but no SRT file was provided.")
    output.parent.mkdir(parents=True, exist_ok=True)
    size = "1280x720" if orientation == "landscape" else "720x1280"
    crop = "1280:720" if orientation == "landscape" else "720:1280"

    if still_image:
        bg_inputs = ["-loop", "1", "-framerate", "2", "-i", str(background)]
    else:
        bg_inputs = ["-stream_loop", "-1", "-i", str(background)]
    vfilter = (f"scale={size}:force_original_aspect_ratio=increase,"
               f"crop={crop},fps={fps},format=yuv420p")

    # Input layout: 0:v = bg, 1:a = audio, then optional template/logo videos.
    cmd_inputs: list[str] = [*bg_inputs, "-i", str(audio)]
    next_idx = 2
    template_idx: int | None = None
    if template is not None and template.exists():
        cmd_inputs += ["-stream_loop", "-1", "-i", str(template)]
        template_idx = next_idx
        next_idx += 1
    logo_idx: int | None = None
    if logo is not None and logo.exists():
        cmd_inputs += ["-i", str(logo)]
        logo_idx = next_idx
        next_idx += 1

    parts = [f"[0:v]{vfilter}[bg]"]
    current = "bg"
    if template_idx is not None:
        marks = _template_marks(duration, template_interval_s,
                                template_duration_s or 30.0)
        parts.append(
            f"[{template_idx}:v]scale={size},fps={fps},format=yuv420p[tmpl]")
        if marks:
            parts.append(f"[{current}][tmpl]overlay=0:0:enable='{marks}'[tbg]")
            current = "tbg"
        else:
            current = "bg"
    if logo_idx is not None:
        lw = max(24, int(1280 * logo_scale)) if orientation == "landscape" else max(
            24, int(720 * logo_scale))
        pos = {
            "top-right": f"W-w-{logo_margin}:{logo_margin}",
            "top-left": f"{logo_margin}:{logo_margin}",
            "bottom-right": f"W-w-{logo_margin}:H-h-{logo_margin}",
            "bottom-left": f"{logo_margin}:H-h-{logo_margin}",
        }.get(logo_position, f"W-w-{logo_margin}:{logo_margin}")
        parts.append(f"[{logo_idx}:v]scale={lw}:-1[lg]")
        parts.append(f"[{current}][lg]overlay={pos}[withlogo]")
        current = "withlogo"
    parts.append(f"[{current}]format=yuv420p[v]")
    if hardsub:
        assert srt is not None  # guarded above; never burn without an SRT
        if not srt.exists() or srt.stat().st_size == 0:
            raise RenderError("HARDSUB_SRT_INVALID",
                              "SRT file is missing or empty.")
        sub = _escape_subtitles_path(srt)
        # Burn into the composited stream in the SAME pass (index-safe:
        # insert before the final format conversion).
        parts.pop()
        parts.append(
            f"[{current}]subtitles={sub}:force_style="
            "'FontName=Noto Sans CJK SC,FontSize=16,Outline=2,"
            "Shadow=0,MarginV=24,Alignment=2'[sub]")
        parts.append("[sub]format=yuv420p[v]")

    cmd = (
        ["ffmpeg", "-v", "error", "-y", *cmd_inputs,
         "-filter_complex", ";".join(parts),
         "-map", "[v]", "-map", "1:a",
         "-c:v", "libx264", "-preset", preset, "-crf", "21",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
         "-shortest", "-threads", str(threads), str(output)]
    )
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    except subprocess.TimeoutExpired:
        raise RenderError("RENDER_TIMEOUT", "ffmpeg render exceeded 2h.")
    if proc.returncode != 0 or not output.exists() or output.stat().st_size == 0:
        raise RenderError("RENDER_FAILED", (proc.stderr or "")[-500:])
    logger.info("rendered %s (%.1fs target)", output.name, duration)
    return output


def _escape_subtitles_path(path: Path) -> str:
    """Escape for the subtitles filter: backslash-colon-quote handling."""
    text = str(path).replace("\\", "/")
    text = text.replace(":", "\\:").replace("'", "\\'")
    return f"'{text}'"


def _template_marks(duration: float, interval_s: float,
                    template_len_s: float) -> str:
    """between() chain: template covers [start, start+len) every interval."""
    if interval_s <= 0 or template_len_s <= 0:
        return ""
    marks = []
    start = interval_s
    while start < duration:
        end = min(duration, start + template_len_s)
        marks.append(f"between(t,{start:.1f},{end:.1f})")
        start += interval_s
    return "+".join(marks)


def make_preview_clip(source: Path, dest: Path, seconds: int = 15) -> Path:
    """Short preview slice for UI (not the publishable output)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(source),
         "-t", str(seconds), "-c", "copy", str(dest)],
        capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RenderError("PREVIEW_FAILED", (proc.stderr or "")[-300:])
    return dest


def fast_mux_loop_video(
    *,
    normalized_video: Path,
    audio: Path,
    output: Path,
    duration: float,
) -> Path:
    """Stream-copy normalized video loop and audio into an MP4 container.

    Zero re-encoding. Completes in ~1-2 seconds regardless of audio duration.
    """
    if duration <= 0:
        raise RenderError("BAD_DURATION", "Audio duration must be positive.")
    if not normalized_video.exists() or normalized_video.stat().st_size == 0:
        raise RenderError("NORMALIZED_VIDEO_MISSING", "Normalized video file is missing or empty.")
    if not audio.exists() or audio.stat().st_size == 0:
        raise RenderError("AUDIO_FILE_MISSING", "Audio file is missing or empty.")

    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-fflags", "+genpts",
        "-stream_loop", "-1", "-i", str(normalized_video),
        "-i", str(audio),
        "-c:v", "copy",
        "-c:a", "copy",
        "-movflags", "+faststart",
        "-shortest",
        "-avoid_negative_ts", "make_zero",
        str(output),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    except subprocess.TimeoutExpired:
        raise RenderError("FAST_MUX_TIMEOUT", "Fast mux timed out.")
    if proc.returncode != 0 or not output.exists() or output.stat().st_size == 0:
        raise RenderError("FAST_MUX_FAILED", (proc.stderr or "")[-500:])

    logger.info("fast muxed %s (%.1fs target)", output.name, duration)
    return output

