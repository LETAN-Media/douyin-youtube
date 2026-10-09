"""Template normalizer and R2 cache service.

Normalizes template (or background video/MOV) to standardized H.264 MP4 once.
If static logo is enabled, bakes logo directly into the normalized video.
Caches optimized template on R2 under audio/pipelines/{pipeline_id}/templates_optimized/.
Subsequent jobs download the cached optimized template in seconds (Cache HIT).
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Any

from app.services import audio_extractor, r2_storage

logger = logging.getLogger("backend-audio.template_cache")


class TemplateCacheError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def get_optimized_template_key(
    pipeline_id: str,
    asset_id: str,
    orientation: str = "landscape",
    logo_id: str | None = None,
    logo_position: str = "top-right",
) -> str:
    logo_suffix = f"_logo_{logo_id}_{logo_position}" if logo_id else "_nologo"
    return f"audio/pipelines/{pipeline_id}/templates_optimized/{asset_id}_{orientation}{logo_suffix}.mp4"


def normalize_template_video(
    input_path: Path,
    output_path: Path,
    *,
    orientation: str = "landscape",
    logo_path: Path | None = None,
    logo_position: str = "top-right",
    logo_scale: float = 0.12,
    logo_margin: int = 24,
    fps: int = 24,
    threads: int = 2,
) -> Path:
    """Normalize input video to standard H.264 closed-GOP MP4 with baked logo (if any)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    size = "1280x720" if orientation == "landscape" else "720x1280"
    crop = "1280:720" if orientation == "landscape" else "720:1280"

    vfilter = (f"scale={size}:force_original_aspect_ratio=increase,"
               f"crop={crop},fps={fps},format=yuv420p")

    cmd_inputs = ["-i", str(input_path)]
    if logo_path is not None and logo_path.exists():
        cmd_inputs += ["-i", str(logo_path)]
        lw = max(24, int(1280 * logo_scale)) if orientation == "landscape" else max(
            24, int(720 * logo_scale))
        pos = {
            "top-right": f"W-w-{logo_margin}:{logo_margin}",
            "top-left": f"{logo_margin}:{logo_margin}",
            "bottom-right": f"W-w-{logo_margin}:H-h-{logo_margin}",
            "bottom-left": f"{logo_margin}:H-h-{logo_margin}",
        }.get(logo_position, f"W-w-{logo_margin}:{logo_margin}")

        filter_complex = (
            f"[0:v]{vfilter}[bg];"
            f"[1:v]scale={lw}:-1[lg];"
            f"[bg][lg]overlay={pos},format=yuv420p[v]"
        )
        map_args = ["-filter_complex", filter_complex, "-map", "[v]"]
    else:
        map_args = ["-vf", vfilter]

    cmd = [
        "ffmpeg", "-v", "error", "-y",
        *cmd_inputs,
        *map_args,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-g", "24",
        "-keyint_min", "24",
        "-sc_threshold", "0",
        "-an",
        "-movflags", "+faststart",
        "-threads", str(threads),
        str(output_path),
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        raise TemplateCacheError("NORMALIZE_TIMEOUT", "Template normalization timed out.")
    if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        raise TemplateCacheError("NORMALIZE_FAILED", (proc.stderr or "")[-500:])

    # Probe result
    probe = audio_extractor.probe_video(output_path)
    if probe.get("duration", 0) <= 0:
        raise TemplateCacheError("NORMALIZE_INVALID", "Normalized template has invalid duration.")

    return output_path


def get_or_create_optimized_template(
    *,
    pipeline_id: str,
    bg_asset: dict[str, Any],
    dest_path: Path,
    orientation: str = "landscape",
    logo_asset: dict[str, Any] | None = None,
    logo_position: str = "top-right",
    threads: int = 2,
    temp_dir: Path | None = None,
) -> tuple[Path, str, float]:
    """Retrieves cached H.264 template from R2 or generates, caches, and returns it.

    Returns:
        (dest_path, "HIT" | "MISS", elapsed_seconds)
    """
    from app.config import settings

    asset_id = bg_asset["id"]
    logo_id = logo_asset["id"] if logo_asset else None
    cache_key = get_optimized_template_key(
        pipeline_id, asset_id, orientation, logo_id, logo_position
    )

    t0 = time.perf_counter()

    # 1. Try cache hit from R2
    if r2_storage.object_exists(cache_key):
        try:
            r2_storage.download_file(cache_key, dest_path)
            probe = audio_extractor.probe_video(dest_path)
            if probe.get("duration", 0) > 0 and probe.get("video_codec") == "h264":
                elapsed = time.perf_counter() - t0
                logger.info("Template cache HIT: %s in %.2fs", cache_key, elapsed)
                return dest_path, "HIT", elapsed
        except Exception as exc:
            logger.warning("Cache hit download failed (%s), regenerating: %s", cache_key, exc)

    # 2. Cache MISS: Download source template from R2
    work_dir = temp_dir or dest_path.parent
    src_suffix = Path(bg_asset.get("file_name") or bg_asset.get("object_key") or "raw.mp4").suffix or ".mp4"
    raw_template = work_dir / f"raw_template_{asset_id}{src_suffix}"

    try:
        r2_storage.download_file(bg_asset["object_key"], raw_template)
    except r2_storage.R2Error as exc:
        raise TemplateCacheError(
            "BACKGROUND_R2_OBJECT_MISSING" if ("DOWNLOAD_FAILED" in exc.code or "404" in str(exc)) else exc.code,
            f"Cannot download background asset from R2: {exc}"
        )

    # Download logo if provided
    logo_local: Path | None = None
    if logo_asset and logo_asset.get("object_key"):
        logo_suffix = Path(logo_asset.get("file_name") or logo_asset.get("object_key") or "logo.png").suffix or ".png"
        logo_local = work_dir / f"logo_{logo_asset['id']}{logo_suffix}"
        try:
            r2_storage.download_file(logo_asset["object_key"], logo_local)
        except Exception as exc:
            logger.warning("Could not download logo for template normalization: %s", exc)
            logo_local = None

    # Normalize video
    normalize_template_video(
        raw_template,
        dest_path,
        orientation=orientation,
        logo_path=logo_local,
        logo_position=logo_position,
        threads=threads,
    )

    # Upload to R2 cache if R2 configured
    if settings.r2_configured():
        try:
            r2_storage.upload_file(dest_path, cache_key, content_type="video/mp4")
            logger.info("Uploaded optimized template to R2 cache: %s", cache_key)
        except Exception as exc:
            logger.warning("Could not upload optimized template to R2: %s", exc)

    elapsed = time.perf_counter() - t0
    logger.info("Template cache MISS: normalized and cached %s in %.2fs", cache_key, elapsed)
    return dest_path, "MISS", elapsed
