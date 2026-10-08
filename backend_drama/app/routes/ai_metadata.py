"""Per-pipeline AI YouTube metadata settings + preview."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import require_admin
from ..db.repositories import ai_metadata as repo
from ..db.repositories import drama as drama_repo
from ..db.repositories import processing as proc_repo
from ._common import _err

router = APIRouter(prefix="/api/drama", tags=["drama-ai-metadata"])


class AiSettingsUpdate(BaseModel):
    enabled: bool | None = None
    language: str | None = None
    generate_title: bool | None = None
    generate_description: bool | None = None
    generate_hashtags: bool | None = None
    system_prompt: str | None = None
    title_template: str | None = None
    description_template: str | None = None
    locked_hashtags: list[str] | str | None = None
    model_override: str | None = None
    expected_config_version: int | None = None


class AiPreviewRequest(BaseModel):
    series_id: str | None = None
    job_id: str | None = None
    language: str | None = None
    force_regenerate: bool = Field(default=False)


def _public(cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "pipeline_id": cfg.get("pipeline_id"),
        "enabled": bool(cfg.get("enabled")),
        "language": cfg.get("language") or "vi",
        "generate_title": bool(cfg.get("generate_title", True)),
        "generate_description": bool(cfg.get("generate_description", True)),
        "generate_hashtags": bool(cfg.get("generate_hashtags", True)),
        "system_prompt": cfg.get("system_prompt"),
        "title_template": cfg.get("title_template"),
        "description_template": cfg.get("description_template"),
        "locked_hashtags": cfg.get("locked_hashtags") or [],
        "model_override": cfg.get("model_override"),
        "config_version": int(cfg.get("config_version") or 1),
        "created_at": cfg.get("created_at"),
        "updated_at": cfg.get("updated_at"),
    }


@router.get("/pipelines/{pipeline_id}/ai-settings")
async def get_ai_settings(pipeline_id: str, _: None = Depends(require_admin)):
    if not drama_repo.get_pipeline(pipeline_id):
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    return _public(repo.get_settings(pipeline_id))


@router.put("/pipelines/{pipeline_id}/ai-settings")
async def update_ai_settings(
    pipeline_id: str, payload: AiSettingsUpdate, _: None = Depends(require_admin)
):
    if not drama_repo.get_pipeline(pipeline_id):
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    data = payload.model_dump(exclude_none=True)
    if "language" in data:
        data["language"] = repo.normalize_language(data["language"])
    try:
        cfg = repo.upsert_settings(pipeline_id, **data)
    except repo.VersionConflict as exc:
        raise _err(409, "SETTINGS_VERSION_CONFLICT", str(exc))
    return _public(cfg)


@router.post("/pipelines/{pipeline_id}/ai-settings/reset")
async def reset_ai_settings(pipeline_id: str, _: None = Depends(require_admin)):
    if not drama_repo.get_pipeline(pipeline_id):
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    return _public(repo.reset_settings(pipeline_id))


@router.post("/pipelines/{pipeline_id}/ai-metadata/preview")
async def preview_ai_metadata(
    pipeline_id: str, payload: AiPreviewRequest, _: None = Depends(require_admin)
):
    from ..services.drama_ai_metadata import (
        AI_DISABLED_FOR_PIPELINE,
        CONFIG_MISSING,
        MetadataError,
        ensure_drama_ai_metadata,
    )

    if not drama_repo.get_pipeline(pipeline_id):
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
    cfg = repo.get_settings(pipeline_id)
    if not cfg.get("enabled"):
        raise _err(400, AI_DISABLED_FOR_PIPELINE, "AI Metadata đang tắt cho pipeline này.")
    language = repo.normalize_language(payload.language or cfg.get("language"))

    job: dict[str, Any] | None = None
    override = False
    previous_language = cfg.get("language") or "vi"
    if payload.job_id:
        job = proc_repo.get_job(payload.job_id)
        if job is None or job.get("pipeline_id") != pipeline_id:
            raise _err(404, "JOB_NOT_FOUND", "Job không tồn tại trong pipeline này.")
    else:
        series_id = (payload.series_id or "").strip()
        if not series_id:
            raise _err(400, "SERIES_REQUIRED", "Cần series_id hoặc job_id để tạo thử.")
        series = drama_repo.get_series(series_id)
        if series is None:
            raise _err(404, "SERIES_NOT_FOUND", "Series không tồn tại.")
        job = {
            "id": f"preview-{pipeline_id}-{series_id}-{language}",
            "pipeline_id": pipeline_id,
            "series_id": series_id,
            "processing_mode": (
                proc_repo.get_settings(pipeline_id) or {}
            ).get("processing_mode") or "direct_merge",
            "episode_start": None,
            "episode_end": None,
        }
        # Preview with an explicit language override: apply temporarily,
        # then restore so previewing never changes the saved pipeline language.
        override = language != previous_language
        if override:
            repo.upsert_settings(pipeline_id, language=language)
    try:
        result = await ensure_drama_ai_metadata(
            job, force_regenerate=payload.force_regenerate
        )
    except MetadataError as exc:
        if override:
            repo.upsert_settings(pipeline_id, language=previous_language)
        if exc.code == CONFIG_MISSING:
            raise _err(503, exc.code, "AI chưa được cấu hình (thiếu TOOLNET_* trên server).")
        raise _err(502, exc.code, str(exc)[:500])
    finally:
        if override:
            repo.upsert_settings(pipeline_id, language=previous_language)
    return {
        "title": result.metadata.title,
        "description": result.metadata.description,
        "hashtags": result.metadata.hashtags,
        "language": language,
        "model": result.model,
        "cached": result.cached,
    }
