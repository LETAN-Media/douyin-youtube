from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import require_admin
from app.db.repositories import audio as audio_repo
from app.db.repositories import jobs as jobs_repo
from app.db.repositories import pipelines as pipe_repo
from app.db.repositories import sources as src_repo

router = APIRouter(prefix="/api/audio", tags=["audio-jobs"])


def _err(status: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": error, "message": message})


class ManualCreate(BaseModel):
    facebook_url: str = Field(min_length=8)
    destination_id: str | None = None
    title: str | None = None
    description: str | None = None
    hashtags: list[str] | None = None
    background_asset_id: str | None = None


@router.get("/pipelines/{pipeline_id}/jobs")
async def list_jobs(pipeline_id: str, limit: int = 50,
                    _: None = Depends(require_admin)):
    if pipe_repo.get_pipeline(pipeline_id) is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    return {"items": jobs_repo.list_jobs(pipeline_id, limit=min(limit, 200))}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, _: None = Depends(require_admin)):
    job = jobs_repo.get_job(job_id)
    if job is None:
        return _err(404, "JOB_NOT_FOUND", "Job không tồn tại.")
    return {**job, "events": jobs_repo.job_events(job_id)}


@router.post("/pipelines/{pipeline_id}/manual", status_code=201)
async def manual_create(pipeline_id: str, body: ManualCreate,
                        _: None = Depends(require_admin)):
    if pipe_repo.get_pipeline(pipeline_id) is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    from app.services import facebook_urls

    try:
        canonical = facebook_urls.canonicalize_facebook_url(body.facebook_url)
    except facebook_urls.FacebookUrlError as exc:
        return _err(400, "INVALID_URL", str(exc))
    fb_id = facebook_urls.extract_facebook_video_id(canonical)
    # Duplicate protection (manual included): never re-queue published items.
    from app.db.client import get_client

    if fb_id:
        pub = get_client().execute(
            "SELECT youtube_url FROM audio_publications "
            "WHERE pipeline_id = ? AND facebook_video_id = ? LIMIT 1",
            (pipeline_id, fb_id)).fetchone()
        if pub:
            return {"duplicate": True, "youtube_url": pub["youtube_url"]}
    item, _ = src_repo.upsert_inventory_item(pipeline_id, None, fb_id, canonical)
    job = jobs_repo.create_job(pipeline_id, inventory_id=item["id"], mode="manual")
    if body.title or body.description or body.hashtags:
        import json

        jobs_repo.update_job(
            job["id"], ai_title=body.title,
            ai_description=body.description or "",
            ai_hashtags_json=json.dumps(body.hashtags or []),
            ai_metadata_status="manual")
    return jobs_repo.get_job(job["id"])


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str, _: None = Depends(require_admin)):
    job = jobs_repo.get_job(job_id)
    if job is None:
        return _err(404, "JOB_NOT_FOUND", "Job không tồn tại.")
    if job.get("youtube_video_id"):
        return _err(409, "ALREADY_PUBLISHED", "Job đã publish, không retry.")
    jobs_repo.update_job(job_id, status="queued", stage="queued",
                         last_error_code=None, last_error_message=None)
    return jobs_repo.get_job(job_id)


@router.get("/pipelines/{pipeline_id}/processing-settings")
async def get_processing(pipeline_id: str, _: None = Depends(require_admin)):
    if pipe_repo.get_pipeline(pipeline_id) is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    from app.services.processing import _processing_settings

    return _processing_settings(pipeline_id)


class ProcessingUpdate(BaseModel):
    subtitle_mode: str | None = None
    srt_auto_generate: bool | None = None
    srt_required: bool | None = None
    srt_object_key: str | None = None
    orientation: str | None = None
    logo_position: str | None = None
    normalize_audio: bool | None = None


@router.put("/pipelines/{pipeline_id}/processing-settings")
async def update_processing(pipeline_id: str, body: ProcessingUpdate,
                            _: None = Depends(require_admin)):
    if pipe_repo.get_pipeline(pipeline_id) is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    from app.db.client import get_client
    from app.db.repositories import now_iso
    from app.services.processing import _processing_settings

    data = body.model_dump(exclude_none=True)
    if "subtitle_mode" in data and data["subtitle_mode"] not in (
            "none", "youtube_captions", "hardsub"):
        return _err(400, "BAD_MODE", "subtitle_mode không hợp lệ.")
    if "orientation" in data and data["orientation"] not in ("landscape",
                                                             "portrait"):
        return _err(400, "BAD_ORIENTATION", "orientation không hợp lệ.")
    current = _processing_settings(pipeline_id)
    merged = {**current, **data}
    client = get_client()
    client.execute(
        "INSERT INTO audio_processing_settings (pipeline_id, subtitle_mode, "
        "srt_auto_generate, srt_required, srt_object_key, orientation, "
        "logo_position, normalize_audio, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(pipeline_id) DO UPDATE SET subtitle_mode=excluded.subtitle_mode, "
        "srt_auto_generate=excluded.srt_auto_generate, "
        "srt_required=excluded.srt_required, "
        "srt_object_key=excluded.srt_object_key, "
        "orientation=excluded.orientation, "
        "logo_position=excluded.logo_position, "
        "normalize_audio=excluded.normalize_audio, "
        "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now')",
        (pipeline_id, merged.get("subtitle_mode", "youtube_captions"),
         1 if merged.get("srt_auto_generate", True) else 0,
         1 if merged.get("srt_required", True) else 0,
         merged.get("srt_object_key"), merged.get("orientation", "landscape"),
         merged.get("logo_position", "top-right"),
         1 if merged.get("normalize_audio", False) else 0, now_iso()))
    client.commit()
    return _processing_settings(pipeline_id)
