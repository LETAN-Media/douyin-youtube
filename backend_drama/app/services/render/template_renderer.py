"""SVG-first template renderer: overlay branding once onto merged video.

Persistent format is SVG (source of truth, stored in R2/assets + Turso
holds id/name/asset_url/geometry). Raster PNG is only a transient working
copy, rasterized ONCE per final video via rsvg-convert (never depends on
ffmpeg SVG support). Rendered ONCE per final video — never per episode.
"""

import logging
import shutil
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

logger = logging.getLogger("backend-drama-template")


class TemplateError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


DEFAULT_CANVAS = (1280, 720)

_UNSAFE_SNIPPETS = (
    "<script", "javascript:", "data:text/html", "data:application/xhtml",
    "onload=", "onerror=", "onclick=", "onmouseover=",
)


def _looks_like_svg_url(url: str) -> bool:
    return url.lower().split("?", 1)[0].split("#", 1)[0].endswith(".svg")


def validate_svg(data: bytes) -> dict[str, Any]:
    """Validate + sanitize-check SVG bytes. Returns {width, height}.

    Rejects: non-XML, non-<svg> root, missing viewBox/size, <script>,
    javascript: URLs, event-handler attributes, and remote references
    (http/https/data: targets in href/src/image). Local fragment refs
    (#...) for gradients/clipPaths/masks are allowed.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TemplateError("TEMPLATE_INVALID_SVG", "Template is not valid UTF-8 SVG.") from exc
    lowered = text.lower()
    for snippet in _UNSAFE_SNIPPETS:
        if snippet in lowered:
            raise TemplateError(
                "TEMPLATE_UNSAFE_SVG",
                f"Template contains forbidden content ({snippet.strip('<')} ).",
            )
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise TemplateError("TEMPLATE_INVALID_SVG", f"Template XML is invalid: {exc}") from exc
    tag = root.tag.lower()
    if "}" in tag:
        tag = tag.rsplit("}", 1)[1]
    if tag != "svg":
        raise TemplateError("TEMPLATE_INVALID_SVG", "Template root element is not <svg>.")
    width = root.get("width")
    height = root.get("height")
    view_box = root.get("viewBox") or root.get("viewbox")
    if not view_box and (not width or not height):
        raise TemplateError(
            "TEMPLATE_INVALID_SVG", "SVG needs a viewBox or width/height."
        )
    for el in root.iter():
        for attr_name, attr_value in el.attrib.items():
            local = attr_name.rsplit("}", 1)[-1].lower()
            if local in ("href", "src") and isinstance(attr_value, str):
                v = attr_value.strip()
                if v.lower().startswith(("http://", "https://", "data:")):
                    raise TemplateError(
                        "TEMPLATE_UNSAFE_SVG",
                        f"Template references remote content ({local}).",
                    )
    dims: dict[str, Any] = {"width": width, "height": height, "viewBox": view_box}
    return dims


def fetch_template_asset(asset_url: str, dest: Path, *, timeout: int = 120) -> Path:
    """Fetch the persistent template asset, preserving its real type.

    SVG stays .svg (validated); raster PNG/JPG is accepted for backward
    compatibility with older presets. Anything else is rejected.
    """
    url = (asset_url or "").strip()
    if url.startswith("file://"):
        src = Path(url[len("file://"):])
        if not src.exists():
            raise TemplateError("TEMPLATE_MISSING", f"Template file not found: {src.name}.")
        if src.suffix.lower() not in (".svg", ".png", ".jpg", ".jpeg"):
            raise TemplateError(
                "TEMPLATE_INVALID_SVG",
                f"Unsupported persistent template type: {src.suffix or 'unknown'}.",
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Preserve the real extension so downstream steps never mistake
        # SVG bytes for a PNG file.
        typed_dest = dest.parent / (dest.stem + src.suffix.lower())
        shutil.copyfile(src, typed_dest)
        return typed_dest
    if not url.lower().startswith(("http://", "https://")):
        raise TemplateError("TEMPLATE_MISSING", "Template asset URL is not http(s)/file.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status not in (200,):
                raise TemplateError("TEMPLATE_MISSING", f"Template fetch HTTP {resp.status}.")
            ctype = (resp.headers.get("Content-Type", "") or "").lower()
            body = resp.read()
    except TemplateError:
        raise
    except Exception as exc:
        raise TemplateError("TEMPLATE_MISSING", f"Cannot fetch template: {exc}") from exc
    if not body:
        raise TemplateError("TEMPLATE_MISSING", "Template download is empty.")
    if "svg" in ctype or _looks_like_svg_url(url):
        typed_dest = dest.parent / (dest.stem + ".svg")
    elif any(k in ctype for k in ("png", "jpeg", "jpg")):
        typed_dest = dest.parent / (dest.stem + ".png")
    else:
        raise TemplateError(
            "TEMPLATE_INVALID_SVG", f"Unsupported template Content-Type: {ctype or 'missing'}."
        )
    typed_dest.write_bytes(body)
    return typed_dest


def rasterize_svg(svg_path: Path, png_path: Path, *, width: int, height: int,
                  timeout: int = 300) -> Path:
    """rsvg-convert template_source.svg -> PNG at the EXACT final canvas size.

    Alpha/transparency preserved. Never depends on ffmpeg SVG support.
    """
    if svg_path.suffix.lower() != ".svg":
        raise TemplateError("TEMPLATE_INVALID_SVG", "Raster input must be .svg.")
    if width <= 0 or height <= 0:
        raise TemplateError("TEMPLATE_INVALID_SVG", "Raster size must be positive.")
    png_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "rsvg-convert",
        "--width", str(width),
        "--height", str(height),
        "--format", "png",
        "--output", str(png_path),
        str(svg_path),
    ]
    try:
        subprocess.run(cmd, check=True, timeout=timeout,
                       capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise TemplateError(
            "TEMPLATE_RENDER_FAILED", "rsvg-convert is not installed."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise TemplateError("TEMPLATE_RENDER_FAILED", "SVG rasterize timed out.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "")[:300]
        raise TemplateError(
            "TEMPLATE_RENDER_FAILED", f"SVG rasterize failed. {detail}"
        ) from exc
    if not png_path.exists() or png_path.stat().st_size <= 0:
        raise TemplateError("TEMPLATE_RENDER_FAILED", "SVG rasterize produced no output.")
    return png_path


def render_template(
    merged_path: Path,
    template: dict[str, Any] | None,
    output: Path,
    *,
    workdir: Path | None = None,
    timeout: int = 1800,
) -> Path:
    """Overlay template frame onto merged video. No template -> copy-through.

    Flow: fetch SVG (validated) -> rasterize ONCE at canvas size ->
    overlay once -> final.mp4. Content is fitted (aspect-preserved) into
    the content box — never stretched. Both temp files are removed.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    if not template:
        shutil.copyfile(merged_path, output)
        return output
    canvas_w = int(template.get("canvas_width") or DEFAULT_CANVAS[0])
    canvas_h = int(template.get("canvas_height") or DEFAULT_CANVAS[1])
    cw = int(template.get("content_width") or canvas_w)
    ch = int(template.get("content_height") or canvas_h)
    cx = int(template.get("content_x") or 0)
    cy = int(template.get("content_y") or 0)
    if min(canvas_w, canvas_h, cw, ch) <= 0 or cx < 0 or cy < 0:
        raise TemplateError("TEMPLATE_MISSING", "Template geometry is invalid.")
    tmp = workdir or output.parent
    tmp.mkdir(parents=True, exist_ok=True)
    fetched = fetch_template_asset(str(template.get("asset_url") or ""), tmp / "template_source")
    png_path = tmp / "template_frame.png"
    try:
        if fetched.suffix.lower() == ".svg":
            validate_svg(fetched.read_bytes())
            rasterize_svg(fetched, png_path, width=canvas_w, height=canvas_h)
        else:
            # Backward-compatible raster preset (older PNG/JPG templates).
            png_path.write_bytes(fetched.read_bytes())
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
            "-i", str(png_path),
            "-filter_complex", vf,
            "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-c:a", "aac", str(output),
        ]
        try:
            subprocess.run(cmd, check=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise TemplateError("TEMPLATE_RENDER_FAILED", "Template render timed out.") from exc
        except subprocess.CalledProcessError as exc:
            raise TemplateError("TEMPLATE_RENDER_FAILED", "ffmpeg template overlay failed.") from exc
        if not output.exists() or output.stat().st_size <= 0:
            raise TemplateError("TEMPLATE_RENDER_FAILED", "Template render produced no output.")
        logger.info("template %s applied -> %s", template.get("id"), output)
        return output
    finally:
        # Remove both temp copies (source + raster). The persistent
        # original stays in R2/assets + Turso.
        for temp_file in (fetched, png_path):
            try:
                temp_file.unlink(missing_ok=True)
            except Exception:
                pass
