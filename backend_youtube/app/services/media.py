import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger("backend-youtube.media")


class MediaError(Exception):
    pass


@dataclass
class MediaInfo:
    url: str
    duration_seconds: float | None
    width: int | None
    height: int | None
    file_size_bytes: int | None
    mime_type: str | None
    resolution: str | None
    local_path: str | None
    title: str | None
    thumbnail_url: str | None
    provider: str
    provider_id: str | None
    raw: dict | None


def _yt_dlp_path() -> str | None:
    return shutil.which("yt-dlp") or shutil.which("yt_dlp")


def _ffprobe_path() -> str | None:
    return shutil.which("ffprobe")


def _ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def _run(cmd: list[str], timeout: int = 120) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError as exc:
        raise MediaError(f"Tool not found: {exc.filename}") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"Tool timed out: {' '.join(cmd)}") from exc


def _probe(local_path: str) -> dict[str, Any]:
    ffprobe = _ffprobe_path()
    if not ffprobe:
        return {"duration_seconds": None, "width": None, "height": None, "file_size_bytes": None, "mime_type": None, "resolution": None}
    rc, out, _err = _run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,codec_name,duration:format=duration,size", "-of", "json", local_path], timeout=60)
    if rc != 0 or not out:
        return {"duration_seconds": None, "width": None, "height": None, "file_size_bytes": None, "mime_type": None, "resolution": None}
    import json
    data = json.loads(out)
    fmt = data.get("format", {})
    stream = (data.get("streams") or [{}])[0]
    duration = None
    for v in (fmt.get("duration"), stream.get("duration")):
        if v:
            try:
                duration = float(v)
            except ValueError:
                pass
    width = stream.get("width")
    height = stream.get("height")
    mime = stream.get("codec_name")
    size = fmt.get("size")
    file_size = int(size) if size else None
    resolution = f"{width}x{height}" if width and height else None
    return {
        "duration_seconds": duration,
        "width": width,
        "height": height,
        "file_size_bytes": file_size,
        "mime_type": mime,
        "resolution": resolution,
    }


async def _fetch_fastsaver_info(client: httpx.AsyncClient, url: str) -> dict:
    base, api_key = settings.require_fastsaver()
    resp = await client.get(
        f"{base}/info",
        params={"url": url},
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        timeout=httpx.Timeout(settings.FASTSAVER_TIMEOUT),
    )
    if resp.status_code != 200:
        raise MediaError(f"FastSaver API error {resp.status_code}: {resp.text}")
    return resp.json()


async def acquire_media(youtube_video_id: str, youtube_url: str, dest_dir: str | None = None) -> MediaInfo:
    os.makedirs(dest_dir or tempfile.gettempdir(), exist_ok=True)
    out_dir = dest_dir or tempfile.gettempdir()
    ytdlp = _yt_dlp_path()
    if ytdlp:
        tmp_name = f"yt_{youtube_video_id}.mp4"
        local_path = os.path.join(out_dir, tmp_name)
        output_template = os.path.join(out_dir, f"yt_{youtube_video_id}.%(ext)s")
        rc, out, err = _run(
            [
                ytdlp,
                "-f", "best[ext=mp4]/best",
                "--no-warnings",
                "--no-playlist",
                "--write-info-json",
                "--write-thumbnail",
                "--restrict-filenames",
                "--concurrent-fragments", "4",
                "-o", output_template,
                youtube_url,
            ],
            timeout=600,
        )
        if rc != 0:
            logger.warning("yt-dlp failed (%s), falling back to FastSaver", err)
            ytdlp = None
        else:
            if os.path.exists(local_path):
                info = _probe(local_path)
                return MediaInfo(
                    url=youtube_url,
                    local_path=local_path,
                    provider="yt-dlp",
                    provider_id=youtube_video_id,
                    duration_seconds=info["duration_seconds"],
                    width=info["width"],
                    height=info["height"],
                    file_size_bytes=info["file_size_bytes"],
                    mime_type=info["mime_type"],
                    resolution=info["resolution"],
                    title=None,
                    thumbnail_url=None,
                    raw={"stdout": out, "stderr": err},
                )
    return await _acquire_via_fastsaver(youtube_video_id, youtube_url, out_dir)


async def _acquire_via_fastsaver(youtube_video_id: str, youtube_url: str, out_dir: str) -> MediaInfo:
    async with httpx.AsyncClient() as client:
        info = await _fetch_fastsaver_info(client, youtube_url)
        download_url = info.get("url") or info.get("download_url")
        if not download_url:
            raise MediaError(f"FastSaver did not return a download URL for {youtube_url}")
        resp = await client.get(download_url, timeout=httpx.Timeout(600.0), follow_redirects=True)
        if resp.status_code != 200:
            raise MediaError(f"Media download failed with {resp.status_code}")
        filename = f"yt_{youtube_video_id}.mp4"
        local_path = os.path.join(out_dir, filename)
        with open(local_path, "wb") as fh:
            fh.write(resp.content)
        size = int(resp.headers.get("content-length", 0) or 0) or os.path.getsize(local_path)
        info_probe = _probe(local_path)
        return MediaInfo(
            url=youtube_url,
            local_path=local_path,
            provider="fastsaver",
            provider_id=youtube_video_id,
            duration_seconds=info_probe["duration_seconds"],
            width=info_probe["width"],
            height=info_probe["height"],
            file_size_bytes=size or info_probe["file_size_bytes"],
            mime_type=info_probe["mime_type"],
            resolution=info_probe["resolution"],
            title=info.get("title"),
            thumbnail_url=info.get("thumbnail") or info.get("thumbnail_url"),
            raw={"fastsaver_info": {k: v for k, v in info.items() if k != "url"}},
        )


def can_reencode() -> bool:
    return bool(_ffmpeg_path())


async def ensure_reel_compatible(local_path: str, max_seconds: int = 90, max_bytes: int = 4_000_000_000) -> str:
    info = _probe(local_path)
    duration = info["duration_seconds"]
    size = info["file_size_bytes"]
    width = info["width"] or 0
    height = info["height"] or 0
    needs_reencode = False
    if duration and duration > max_seconds:
        needs_reencode = True
    if size and size > max_bytes:
        needs_reencode = True
    if width > 1080 or height > 1920:
        needs_reencode = True
    if height > width and (height > 1920 or width > 1080):
        needs_reencode = True
    if not needs_reencode:
        return local_path
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        raise MediaError("ffmpeg not available for re-encoding")
    out_path = local_path.replace(".mp4", "_reel.mp4")
    scale = "-vf scale='min(1080,iw)':'-2':flags=lanczos" if False else f"-vf scale='min(1080,iw)':-2"
    cmd = [
        ffmpeg, "-y", "-i", local_path,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        f"-t", str(max_seconds),
        "-movflags", "+faststart",
        out_path,
    ]
    rc, out, err = _run(cmd, timeout=900)
    if rc != 0:
        raise MediaError(f"ffmpeg re-encode failed: {err}")
    return out_path


def cleanup(local_path: str | None) -> None:
    if not local_path:
        return
    try:
        if os.path.exists(local_path):
            os.remove(local_path)
    except OSError as exc:
        logger.warning("Failed to cleanup %s: %s", local_path, exc)
