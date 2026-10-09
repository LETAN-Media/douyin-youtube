"""Media library: upload/list/delete/enable assets stored in R2."""

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from app.auth import require_admin
from app.db.repositories import audio as repo
from app.db.repositories import pipelines as pipe_repo

router = APIRouter(prefix="/api/audio", tags=["audio-media"])

ALLOWED = {
    "background": {"image/gif", "video/mp4", "image/jpeg", "image/png"},
    "logo": {"image/png", "image/svg+xml", "image/jpeg"},
    "template": {"video/mp4", "video/quicktime"},
}
MAX_UPLOAD_BYTES = 300 * 1024 * 1024


def _err(status: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": error, "message": message})


@router.get("/pipelines/{pipeline_id}/media")
async def list_media(pipeline_id: str, kind: str | None = None,
                     _: None = Depends(require_admin)):
    if pipe_repo.get_pipeline(pipeline_id) is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    from app.services import r2_storage

    items = []
    for asset in repo.list_assets(pipeline_id, kind):
        url = None
        try:
            url = r2_storage.presigned_url(asset["object_key"])
        except Exception:
            url = r2_storage.public_url(asset["object_key"])
        items.append({**asset, "preview_url": url})
    return {"items": items}


@router.post("/pipelines/{pipeline_id}/media", status_code=201)
async def upload_media(pipeline_id: str, kind: str = Form("background"),
                       file: UploadFile = File(...),
                       _: None = Depends(require_admin)):
    if pipe_repo.get_pipeline(pipeline_id) is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    if kind not in ALLOWED:
        return _err(400, "BAD_KIND", "kind must be background, logo or template.")
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from app.services import audio_extractor, r2_storage

    mime = (file.content_type or "").split(";")[0].strip().lower()
    if mime not in ALLOWED[kind] and mime != "application/octet-stream":
        return _err(400, "BAD_TYPE", f"Unsupported content-type: {mime}.")
    with TemporaryDirectory(prefix="audio-upload-") as tmp:
        local = Path(tmp) / (file.filename or "upload")
        size = 0
        with open(local, "wb") as fh:
            while True:
                chunk = await file.read(1024 * 256)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    return _err(400, "TOO_LARGE", "File vượt quá giới hạn.")
                fh.write(chunk)
        object_key = (f"{r2_storage.pipeline_prefix(pipeline_id, kind)}"
                      f"{local.stem[:48]}-{local.stat().st_size}{local.suffix.lower()}")
        width = height = None
        duration = None
        final_local = local
        # GIF -> standardized MP4 loop once, stored in R2 (never decode per job).
        if kind == "background" and local.suffix.lower() == ".gif":
            import subprocess

            mp4 = Path(tmp) / f"{local.stem}.mp4"
            proc = subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-i", str(local),
                 "-vf", "scale=1280:720:force_original_aspect_ratio=increase,"
                        "crop=1280:720,fps=24,format=yuv420p",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                 "-t", "10", str(mp4)],
                capture_output=True, text=True, timeout=600)
            if proc.returncode != 0:
                return _err(400, "GIF_CONVERT_FAILED", "Không chuẩn hóa được GIF.")
            object_key = object_key.rsplit(".", 1)[0] + ".mp4"
            final_local = mp4
            mime = "video/mp4"
        if mime.startswith("video/") or final_local.suffix.lower() == ".mp4":
            try:
                probe = audio_extractor.probe_media(final_local)
            except Exception:
                probe = {}
            duration = probe.get("duration") if isinstance(probe, dict) else None
        try:
            r2_storage.upload_file(final_local, object_key,
                                   content_type=mime or None)
        except r2_storage.R2Error as exc:
            return _err(502, exc.code, str(exc))
        asset = repo.add_asset(pipeline_id, kind, object_key,
                               file_name=file.filename, mime=mime,
                               width=width, height=height,
                               duration_seconds=duration, bytes=size)
    return asset


@router.put("/media/{asset_id}")
async def set_enabled(asset_id: str, enabled: bool,
                      _: None = Depends(require_admin)):
    repo.set_asset_enabled(asset_id, enabled)
    return {"id": asset_id, "enabled": enabled}


@router.delete("/media/{asset_id}")
async def delete(asset_id: str, _: None = Depends(require_admin)):
    from app.services import r2_storage

    asset = repo.delete_asset(asset_id)
    if asset is None:
        return _err(404, "ASSET_NOT_FOUND", "Asset không tồn tại.")
    try:
        r2_storage.delete_object(asset["object_key"])
    except Exception:
        pass
    return {"deleted": True}
