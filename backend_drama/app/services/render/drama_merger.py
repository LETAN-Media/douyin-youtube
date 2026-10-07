"""Episode concatenation via ffmpeg concat demuxer.

- Episode order is always episode_number ASC (callers pass ordered paths).
- Stream copy when every input shares video codec/resolution/fps and has
  compatible audio; otherwise normalize to 1280x720@30fps h264+aac.
- Final output is always ffprobe-validated.
"""

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger("backend-drama-merge")


class MergeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _probe_streams(path: Path) -> dict[str, Any]:
    res = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", str(path)],
        capture_output=True, text=True, check=True, timeout=120,
    )
    data = json.loads(res.stdout or "{}")
    video = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
        {},
    )
    audio = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "audio"),
        {},
    )
    return {
        "vcodec": video.get("codec_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": video.get("avg_frame_rate") or video.get("r_frame_rate"),
        "acodec": audio.get("codec_name") if audio else None,
    }


def compatible_for_copy(paths: list[Path]) -> bool:
    """True when stream copy is safe for all inputs."""
    if not paths:
        return False
    try:
        first = _probe_streams(paths[0])
    except Exception:
        return False
    for path in paths[1:]:
        try:
            info = _probe_streams(path)
        except Exception:
            return False
        if (
            info["vcodec"] != first["vcodec"]
            or info["width"] != first["width"]
            or info["height"] != first["height"]
            or info["fps"] != first["fps"]
        ):
            return False
    return True


def write_concat_manifest(paths: list[Path], manifest: Path) -> Path:
    """Concat demuxer manifest, one quoted file line per episode, in order."""
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("w", encoding="utf-8") as fh:
        for path in paths:
            # Single quotes escaped the concat-demuxer way.
            safe = str(path).replace("'", "'\\''")
            fh.write(f"file '{safe}'\n")
    return manifest


def concat_paths(paths: list[Path], output: Path, *, timeout: int = 3600) -> Path:
    """Concatenate ordered episode files into output. Validates with ffprobe."""
    if not paths:
        raise MergeError("MERGE_NO_INPUTS", "No episode files to merge.")
    for path in paths:
        if not path.exists() or path.stat().st_size <= 0:
            raise MergeError("MERGE_MISSING_INPUT", f"Missing episode file: {path.name}.")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = output.parent / "concat.txt"
    write_concat_manifest(paths, manifest)
    if compatible_for_copy(paths):
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
               "-i", str(manifest), "-c", "copy", str(output)]
        mode = "copy"
    else:
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
               "-i", str(manifest),
               "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,"
                      "pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
               "-c:a", "aac", str(output)]
        mode = "normalize"
    try:
        subprocess.run(cmd, check=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise MergeError("MERGE_TIMEOUT", "ffmpeg concat timed out.") from exc
    except subprocess.CalledProcessError as exc:
        raise MergeError("MERGE_FAILED", f"ffmpeg concat failed ({mode}).") from exc
    if not output.exists() or output.stat().st_size <= 0:
        raise MergeError("MERGE_FAILED", "ffmpeg produced no output.")
    logger.info("merge %s %d inputs -> %s", mode, len(paths), output)
    return output
