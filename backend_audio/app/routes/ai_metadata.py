from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import require_admin
from app.db.repositories import audio as repo
from app.db.repositories import pipelines as pipe_repo

router = APIRouter(prefix="/api/audio", tags=["audio-ai"])

GENRES = ["Audio Ngôn Tình", "Audio Boy Love", "Audio Kinh Dị",
          "Audio Trinh Thám", "Audio Xuyên Không", "Audio Tu Tiên",
          "Audio Tổng Tài", "Audio Tâm Lý", "Custom Genre"]


class AiUpdate(BaseModel):
    enabled: bool | None = None
    language: str | None = None
    genre: str | list[str] | None = None
    generate_title: bool | None = None
    generate_description: bool | None = None
    generate_hashtags: bool | None = None
    system_prompt: str | None = None
    title_template: str | None = None
    description_template: str | None = None
    locked_hashtags: list[str] | str | None = None
    model_override: str | None = None
    expected_config_version: int | None = None


class AiPreview(BaseModel):
    job_id: str | None = None
    inventory_id: str | None = None
    language: str | None = None
    force_regenerate: bool = False


def _public(cfg: dict) -> dict:
    return {
        "pipeline_id": cfg.get("pipeline_id"),
        "enabled": bool(cfg.get("enabled")),
        "language": cfg.get("language") or "vi",
        "genre": cfg.get("genre"),
        "generate_title": bool(cfg.get("generate_title", True)),
        "generate_description": bool(cfg.get("generate_description", True)),
        "generate_hashtags": bool(cfg.get("generate_hashtags", True)),
        "system_prompt": cfg.get("system_prompt"),
        "title_template": cfg.get("title_template"),
        "description_template": cfg.get("description_template"),
        "locked_hashtags": cfg.get("locked_hashtags") or [],
        "model_override": cfg.get("model_override"),
        "config_version": int(cfg.get("config_version") or 1),
        "updated_at": cfg.get("updated_at"),
    }


@router.get("/pipelines/{pipeline_id}/ai-settings")
async def get_ai(pipeline_id: str, _: None = Depends(require_admin)):
    if pipe_repo.get_pipeline(pipeline_id) is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    return {**_public(repo.get_ai_settings(pipeline_id)), "genres": GENRES}


@router.put("/pipelines/{pipeline_id}/ai-settings")
async def update_ai(pipeline_id: str, body: AiUpdate,
                    _: None = Depends(require_admin)):
    if pipe_repo.get_pipeline(pipeline_id) is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    try:
        cfg = repo.upsert_ai_settings(pipeline_id,
                                      **body.model_dump(exclude_none=True))
    except repo.VersionConflict as exc:
        return _err(409, "SETTINGS_VERSION_CONFLICT", str(exc))
    return _public(cfg)


@router.post("/pipelines/{pipeline_id}/ai-settings/reset")
async def reset_ai(pipeline_id: str, _: None = Depends(require_admin)):
    if pipe_repo.get_pipeline(pipeline_id) is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    return _public(repo.reset_ai_settings(pipeline_id))


@router.post("/pipelines/{pipeline_id}/ai-metadata/preview")
async def preview(pipeline_id: str, body: AiPreview,
                  _: None = Depends(require_admin)):
    from app.services import ai_metadata as ai_svc

    if pipe_repo.get_pipeline(pipeline_id) is None:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    cfg = repo.get_ai_settings(pipeline_id)
    if not cfg.get("enabled"):
        return _err(400, "AI_DISABLED", "AI Metadata đang tắt.")
    language = ai_svc.normalize_language(body.language or cfg.get("language"))

    source_title = source_caption = duration = channel = None
    if body.inventory_id:
        from app.db.client import get_client

        row = get_client().execute(
            "SELECT * FROM audio_inventory WHERE id = ?",
            (body.inventory_id,)).fetchone()
        if row is None:
            return _err(404, "INVENTORY_NOT_FOUND", "Inventory không tồn tại.")
        source_title = f"Facebook video {row['facebook_video_id'] or row['id']}"
        source_caption = row["caption"]
        duration = row["duration_seconds"]
    channel = _channel_name(pipeline_id)
    try:
        generated = await ai_svc.generate_metadata(
            ai_svc.AiContext(source_title=source_title or "Audio",
                             source_caption=source_caption,
                             audio_duration_s=duration,
                             channel_name=channel,
                             custom_prompt=cfg.get("system_prompt")),
            {**cfg, "language": language})
    except ai_svc.MetadataError as exc:
        code = 503 if exc.code == "TOOLNET_CONFIG_MISSING" else 502
        return _err(code, exc.code, str(exc))
    return {"title": generated.title, "description": generated.description,
            "hashtags": generated.hashtags, "language": language,
            "model": generated.model, "cached": False}


def _err(status: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": error, "message": message})


def _channel_name(pipeline_id: str) -> str | None:
    for dest in repo.list_destinations(pipeline_id):
        if dest.get("connected"):
            return dest.get("channel_title") or dest.get("channel_id")
    return None
