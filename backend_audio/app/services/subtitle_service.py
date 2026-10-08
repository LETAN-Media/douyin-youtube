"""Subtitles: JianYing ASR bridge (node subprocess, JSON protocol) + chunk stitching.

Mirrors backend_drama/tools/jianying_asr/transcribe.mjs usage: the bridge is
invoked per audio chunk, SRT cues are offset-merged. A pre-uploaded SRT can
be used instead of ASR. No translation unless explicitly enabled elsewhere.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger("backend-audio.subtitles")


class SubtitleError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_CUE_RE = re.compile(
    r"(\d+)\s*\n(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n(.*?)(?=\n\d+\s*\n|\Z)",
    re.DOTALL)


def _to_ms(ts: str) -> int:
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return (int(h) * 3600 + int(m) * 60 + int(s)) * 1000 + int(ms)


def _to_ts(ms: int) -> str:
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt(text: str) -> list[tuple[int, int, str]]:
    cues = []
    for match in _CUE_RE.finditer(text or ""):
        start, end, body = _to_ms(match.group(2)), _to_ms(match.group(3)), match.group(4).strip()
        if end > start and body:
            cues.append((start, end, body))
    return sorted(cues)


def format_srt(cues: list[tuple[int, int, str]]) -> str:
    out = []
    for i, (start, end, body) in enumerate(cues, 1):
        out.append(f"{i}\n{_to_ts(start)} --> {_to_ts(end)}\n{body}\n")
    return "\n".join(out)


def merge_chunks(chunks: list[tuple[float, str]]) -> str:
    """Merge per-chunk SRT files: offset by chunk start, drop overlaps/dupes."""
    merged: list[tuple[int, int, str]] = []
    for offset_s, srt_path in chunks:
        offset_ms = int(offset_s * 1000)
        try:
            cues = parse_srt(Path(srt_path).read_text(encoding="utf-8", errors="replace"))
        except FileNotFoundError:
            continue
        for start, end, body in cues:
            start += offset_ms
            end += offset_ms
            if merged and start < merged[-1][1] - 200:
                continue  # overlap dupe from chunk overlap
            if merged and start < merged[-1][1]:
                start = merged[-1][1]
            if end > start:
                merged.append((start, end, body))
    return format_srt(merged)


def split_plan(duration_s: float, chunk_s: float = 480.0,
               overlap_s: float = 5.0) -> list[tuple[float, float]]:
    """[(start, end)] chunks with small overlap to avoid cut sentences."""
    plan, pos = [], 0.0
    while pos < duration_s:
        end = min(duration_s, pos + chunk_s)
        plan.append((pos, end))
        if end >= duration_s:
            break
        pos = end - overlap_s
    return plan


def transcribe_with_bridge(audio_path: Path, srt_out: Path, language: str = "auto",
                           timeout_ms: int = 600000) -> Path:
    """Run the node JianYing bridge. Raises SubtitleError with typed codes."""
    from app.config import settings

    bridge_dir = (settings.JIANYING_BRIDGE_DIR or "").strip()
    if not bridge_dir:
        raise SubtitleError("ASR_NOT_CONFIGURED",
                            "JIANYING_BRIDGE_DIR is not configured.")
    bridge = Path(bridge_dir) / "transcribe.mjs"
    if not bridge.exists():
        raise SubtitleError("ASR_BRIDGE_MISSING",
                            f"Bridge not found: {bridge}.")
    try:
        proc = subprocess.run(
            ["node", str(bridge), "--input", str(audio_path),
             "--out", str(srt_out), "--timeout-ms", str(timeout_ms)],
            capture_output=True, text=True, timeout=timeout_ms / 1000 + 120)
    except FileNotFoundError:
        raise SubtitleError("NODE_MISSING", "node is not installed.")
    except subprocess.TimeoutExpired:
        raise SubtitleError("ASR_TIMEOUT", "JianYing bridge timed out.")
    line = (proc.stdout or "").strip().splitlines()
    result = json.loads(line[-1]) if line else {}
    if not result.get("ok"):
        raise SubtitleError(result.get("code") or "ASR_FAILED",
                            str(result.get("message") or "")[:300])
    cues = parse_srt(Path(result.get("srt_path") or srt_out).read_text(
        encoding="utf-8", errors="replace"))
    if not cues:
        raise SubtitleError("ASR_EMPTY", "ASR produced no cues.")
    logger.info("asr ok: %d cues", len(cues))
    return srt_out


def slice_audio_for_chunk(audio_path: Path, start_s: float, end_s: float,
                          dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", str(start_s), "-i", str(audio_path),
         "-t", str(end_s - start_s), "-c:a", "copy", str(dest)],
        capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise SubtitleError("CHUNK_SLICE_FAILED", (proc.stderr or "")[-200:])
    return dest
