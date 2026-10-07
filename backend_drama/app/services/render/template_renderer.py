"""Template/frame renderer: overlay branding once onto the merged video.

Input: merged.mp4 (one long video) + template asset (image) + geometry.
Output: final.mp4. Rendered ONCE per final video — never per episode.

Template asset lives in object storage (or any URL); only a local working
copy is used here. Geometry comes from the pipeline's template preset,
with sane defaults when unconfigured.
"""

import logging
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger("backend-drama-template")


class TemplateError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


DEFAULT_CANVAS = (1280, 720)


def fetch_template_asset(asset_url: str, dest: Path, *, timeout: int = 120) -> Path:
    """Fetch the persistent template asset to a local working copy."""
    url = (asset_url or "").strip()
    if url.startswith("file://"):
        src = Path(url[len("file://"):])
        if not src.exists():
            raise TemplateError("TEMPLATE_MISSING", f"Template file not found: {src.name}.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        return dest
    if not url.lower().startswith(("http://", "https://")):
        raise TemplateError("TEMPLATE_MISSING", "Template asset URL is not http(s)/file.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status not in (200,):
                raise TemplateError("TEMPLATE_MISSING", f"Template fetch HTTP {resp.status}.")
            ctype = (resp.headers.get("Content-Type", "") or "").lower()
            if "image/" not in ctype and "octet-stream" not in ctype:
                raise TemplateError("TEMPLATE_MISSING", f"Unexpected template type: {ctype or 'missing'}.")
            with dest.open("wb") as fh:
                shutil.copyfileobj(resp, fh, length=1024 * 256)
    except TemplateError:
        raise
    except Exception as exc:
        raise TemplateError("TEMPLATE_MISSING", f"Cannot fetch template: {exc}") from exc
    if not dest.exists() or dest.stat().st_size <= 0:
        raise TemplateError("TEMPLATE_MISSING", "Template download is empty.")
    return dest


def render_template(
    merged_path: Path,
    template: dict[str, Any] | None,
    output: Path,
    *,
    workdir: Path | None = None,
    timeout: int = 1800,
) -> Path:
    """Overlay template frame onto merged video. No template -> copy-through.

    Modes: overlay (default) composites the frame over the fitted video;
    frame/fullscreen currently behave as overlay (documented for presets).
    Content is fitted (aspect-preserved) into the content box — never
    stretched.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    if not template:
        shutil.copyfile(merged_path, output)
        return output
    canvas_w = int(template.get("canvas_width") or DEFAULT_CANVAS[0])
    canvas_h = int(template.get("canvas_height") or DEFAULT_CANVAS[1])
    cx = int(template.get("content_x") or 0)
    cy = int(template.get("content_y") or 0)
    cw = int(template.get("content_width") or canvas_w)
    ch = int(template.get("content_height") or canvas_h)
    if cw <= 0 or ch <= 0 or canvas_w <= 0 or canvas_h <= 0:
        raise TemplateError("TEMPLATE_MISSING", "Template geometry is invalid.")
    tmp = workdir or output.parent
    tmp.mkdir(parents=True, exist_ok=True)
    frame_path = tmp / "template_frame.png"
    fetch_template_asset(str(template.get("asset_url") or ""), frame_path)
    vf = (
        f"[0:v]scale={cw}:{ch}:force_original_aspect_ratio=decrease,"
        f"pad={cw}:{ch}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,"
        f"pad={canvas_w}:{canvas_h}:{cx}:{cy}:black[content];"
        f"[1:v]scale={canvas_w}:{canvas_h}[frame];"
        f"[content][frame]overlay=0:0,setsar=1[v]"
    )
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-i", str(merged_path),
        "-i", str(frame_path),
        "-filter_complex", vf,
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-c:a", "aac", str(output),
    ]
    try:
        subprocess.run(cmd, check=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise TemplateError("TEMPLATE_RENDER_TIMEOUT", "Template render timed out.") from exc
    except subprocess.CalledProcessError as exc:
        raise TemplateError("TEMPLATE_RENDER_FAILED", "ffmpeg template overlay failed.") from exc
    finally:
        try:
            frame_path.unlink(missing_ok=True)
        except Exception:
            pass
    if not output.exists() or output.stat().st_size <= 0:
        raise TemplateError("TEMPLATE_RENDER_FAILED", "Template render produced no output.")
    logger.info("template %s applied -> %s", template.get("id"), output)
    return output
