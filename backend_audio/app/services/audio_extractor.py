"""Audio extraction via ffmpeg CLI (stream copy first, transcode only if needed)."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("backend-audio.audio")


class AudioError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def probe_media(path: Path) -> dict:
    """ffprobe: streams, duration, audio codec. Raises AudioError on failure."""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_streams", "-show_format", str(path)],
            capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise AudioError("FFMPEG_MISSING", "ffprobe is not installed.")
    except subprocess.TimeoutExpired:
        raise AudioError("PROBE_TIMEOUT", "ffprobe timed out.")
    if proc.returncode != 0:
        raise AudioError("PROBE_FAILED", (proc.stderr or "")[:300])
    try:
        info = json.loads(proc.stdout or "{}")
    except Exception:
        raise AudioError("PROBE_FAILED", "ffprobe returned invalid JSON.")
    streams = info.get("streams") or []
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if not audio:
        raise AudioError("NO_AUDIO_STREAM", "Video has no audio stream.")
    duration = float((info.get("format") or {}).get("duration") or 0)
    return {
        "duration": duration,
        "audio_codec": audio[0].get("codec_name"),
        "audio_channels": audio[0].get("channels"),
        "audio_sample_rate": audio[0].get("sample_rate"),
    }


def extract_audio(source: Path, dest: Path, normalize: bool = False,
                  threads: int = 2) -> Path:
    """Extract audio to .m4a: AAC stream-copy when possible, else AAC transcode.

    Returns dest. Raises SOURCE_AUDIO_MISSING when the source has no audio,
    EXTRACT_FAILED on ffmpeg errors. Never produces MP3.
    """
    if dest.suffix.lower() != ".m4a":
        raise AudioError("BAD_DEST_FORMAT", "Intermediate audio must be .m4a.")
    try:
        info = probe_media(source)
    except AudioError as exc:
        if exc.code == "NO_AUDIO_STREAM":
            raise AudioError("SOURCE_AUDIO_MISSING",
                             "Source video has no audio stream.")
        raise
    dest.parent.mkdir(parents=True, exist_ok=True)
    codec = (info.get("audio_codec") or "").lower()
    if not normalize and codec == "aac":
        method = "STREAM_COPY"
        cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y",
               "-i", str(source), "-map", "0:a:0", "-vn", "-c:a", "copy",
               str(dest)]
    else:
        # Filters require decode; non-AAC needs a compatible M4A codec.
        method = "AAC_TRANSCODE"
        cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y",
               "-i", str(source), "-map", "0:a:0", "-vn", "-c:a", "aac",
               "-b:a", "128k", "-threads", str(threads)]
        if normalize:
            cmd += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
        cmd.append(str(dest))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    except subprocess.TimeoutExpired:
        raise AudioError("EXTRACT_TIMEOUT", "ffmpeg extract exceeded 1h.")
    if proc.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        raise AudioError("EXTRACT_FAILED", (proc.stderr or "")[-300:])
    out = probe_media(dest)
    if not out["duration"] or out["duration"] <= 0:
        raise AudioError("EXTRACT_FAILED", "Extracted audio has no duration.")
    src_duration = info.get("duration") or 0
    if src_duration > 0 and abs(out["duration"] - src_duration) > max(
            2.0, src_duration * 0.05):
        raise AudioError("EXTRACT_FAILED",
                         "Extracted duration does not match source.")
    logger.info("audio extracted: %.1fs codec=%s method=%s", out["duration"],
                out.get("audio_codec"), method)
    return dest
