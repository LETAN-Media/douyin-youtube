"""AI metadata endpoints (Task 8A & Task 9). Admin-only generation & settings, public-safe reads."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import require_admin
from ..db.repositories import ai_metadata as ai_repo
from ..db.repositories import ai_settings as ai_settings_repo
from ..db.repositories import pipelines, reels
from ..services.facebook_ai_metadata import (
    MetadataError,
    apply_description_template,
    apply_locked_hashtags,
    apply_title_template,
    ensure_ai_metadata,
)

router = APIRouter(prefix="/api/facebook", tags=["facebook-ai"])

ERROR_STATUS = {
    "TOOLNET_CONFIG_MISSING": 500,
    "TOOLNET_AUTH_FAILED": 502,
    "TOOLNET_RATE_LIMITED": 429,
    "TOOLNET_TIMEOUT": 504,
    "TOOLNET_UPSTREAM_ERROR": 502,
    "AI_INVALID_RESPONSE": 502,
    "AI_INSUFFICIENT_CONTEXT": 422,
    "AI_DISABLED_FOR_PIPELINE": 422,
}


def _err(status_code: int, error: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": error, "message": message})


def _metadata_response(row: dict) -> dict:
    return {
        "title": row.get("title"),
        "description": row.get("description"),
        "hashtags": row.get("hashtags", []),
    }


class AiSettingsUpdate(BaseModel):
    enabled: bool = True
    system_prompt: str = ""
    title_template: str = "{title}"
    description_template: str = "{description}\n\n{hashtags}"
    locked_hashtags: list[str] = Field(default_factory=list)
    language: str = "vi"


class AiSettingsPreviewRequest(BaseModel):
    title_template: str = "{title}"
    description_template: str = "{description}\n\n{hashtags}"
    locked_hashtags: list[str] = Field(default_factory=list)
    sample_title: str | None = None
    sample_description: str | None = None
    sample_hashtags: list[str] | None = None
    sample_source_url: str | None = None


BLOCKED_SYSTEM_PROMPT_PATTERNS = [
    r"(?i)do not return json",
    r"(?i)don't return json",
    r"(?i)no json",
    r"(?i)output xml",
    r"(?i)raw text only",
    r"(?i)ignore (system|previous) instructions",
    r"(?i)không (trả|dùng|xuất) json",
]


def validate_ai_settings_input(body: AiSettingsUpdate) -> None:
    # title_template
    tt = body.title_template.strip()
    if not tt or len(tt) > 200:
        raise _err(422, "INVALID_TITLE_TEMPLATE", "Title template must be between 1 and 200 characters.")
    if "{title}" not in tt:
        raise _err(422, "INVALID_TITLE_TEMPLATE", "Title template must contain {title}.")

    # description_template
    dt = body.description_template.strip()
    if not dt or len(dt) > 2000:
        raise _err(422, "INVALID_DESCRIPTION_TEMPLATE", "Description template must be between 1 and 2000 characters.")
    placeholders = re.findall(r"\{([^{}]+)\}", dt)
    allowed = {"description", "hashtags", "source_url"}
    invalid = [p for p in placeholders if p not in allowed]
    if invalid:
        raise _err(
            422,
            "INVALID_DESCRIPTION_TEMPLATE",
            f"Unsupported placeholder(s): {', '.join(invalid)}. Supported: {{description}}, {{hashtags}}, {{source_url}}.",
        )

    # locked_hashtags
    if len(body.locked_hashtags) > 30:
        raise _err(422, "INVALID_LOCKED_HASHTAGS", "Cannot have more than 30 locked hashtags.")
    for tag in body.locked_hashtags:
        if len(tag) > 50:
            raise _err(422, "INVALID_LOCKED_HASHTAGS", f"Hashtag '{tag[:20]}...' exceeds 50 characters.")

    # system_prompt
    sp = body.system_prompt.strip()
    if len(sp) > 2000:
        raise _err(422, "INVALID_SYSTEM_PROMPT", "System prompt must be at most 2000 characters.")
    for pat in BLOCKED_SYSTEM_PROMPT_PATTERNS:
        if re.search(pat, sp):
            raise _err(
                422,
                "INVALID_SYSTEM_PROMPT",
                "Custom system prompt violates safety or JSON contract rules.",
            )

    # language
    lang = body.language.strip()
    if not lang or len(lang) > 10:
        raise _err(422, "INVALID_LANGUAGE", "Language must be between 1 and 10 characters.")


@router.post("/reels/{reel_db_id}/ai-metadata/generate")
async def generate_metadata(reel_db_id: str, _: None = Depends(require_admin)) -> dict:
    reel = await reels.get_reel(reel_db_id)
    if reel is None:
        raise _err(404, "REEL_NOT_FOUND", "Reel not found")

    try:
        ensured = await ensure_ai_metadata(reel)
    except MetadataError as exc:
        await ai_repo.mark_failed(reel_db_id, f"{exc.code}: {exc}")
        raise _err(ERROR_STATUS.get(exc.code, 500), exc.code, str(exc))
    return {
        "ok": True,
        "reel_id": reel.get("reel_id"),
        "status": "generated",
        "metadata": {
            "title": ensured.metadata.title,
            "description": ensured.metadata.description,
            "hashtags": ensured.metadata.hashtags,
        },
        "model": ensured.model,
        "cached": ensured.cached,
        "usage": ensured.usage,
    }


@router.get("/reels/{reel_db_id}/ai-metadata")
async def get_metadata(reel_db_id: str, _: None = Depends(require_admin)) -> dict:
    row = await ai_repo.get_for_reel(reel_db_id)
    if row is None:
        raise _err(404, "METADATA_NOT_FOUND", "No AI metadata for this reel.")
    return {
        "reel_db_id": row["reel_db_id"],
        "status": row["status"],
        "metadata": _metadata_response(row),
        "model": row.get("model"),
    }


@router.get("/pipelines/{pipeline_id}/ai-metadata/stats")
async def ai_stats(pipeline_id: str, _: None = Depends(require_admin)) -> dict:
    return await ai_repo.pipeline_stats(pipeline_id)


@router.get("/pipelines/{pipeline_id}/ai-metadata/sample")
async def ai_sample(pipeline_id: str, _: None = Depends(require_admin)) -> dict:
    pipeline = await pipelines.get_pipeline(pipeline_id)
    if pipeline is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found.")
    sample = await ai_repo.get_sample_for_pipeline(pipeline_id)
    if sample is None:
        return {"ok": True, "sample": None}
    return {
        "ok": True,
        "sample": {
            "reel_db_id": sample["reel_db_id"],
            "status": sample["status"],
            "metadata": _metadata_response(sample),
            "model": sample.get("model"),
            "generated_at": sample.get("generated_at"),
        },
    }


@router.get("/pipelines/{pipeline_id}/ai-settings")
async def get_ai_settings(pipeline_id: str, _: None = Depends(require_admin)) -> dict:
    pipeline = await pipelines.get_pipeline(pipeline_id)
    if pipeline is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found.")
    return await ai_settings_repo.get_settings(pipeline_id)


@router.put("/pipelines/{pipeline_id}/ai-settings")
async def update_ai_settings(
    pipeline_id: str,
    body: AiSettingsUpdate,
    _: None = Depends(require_admin),
) -> dict:
    pipeline = await pipelines.get_pipeline(pipeline_id)
    if pipeline is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found.")
    validate_ai_settings_input(body)
    from ..config import settings as app_settings

    # Store config_hash with the real ToolNet model so it matches the
    # hash the scheduler/publisher/worker recompute. A model-less hash
    # would never match and silently stall scheduling.
    return await ai_settings_repo.upsert_settings(
        pipeline_id=pipeline_id,
        enabled=body.enabled,
        system_prompt=body.system_prompt.strip(),
        title_template=body.title_template.strip(),
        description_template=body.description_template.strip(),
        locked_hashtags=body.locked_hashtags,
        language=body.language.strip(),
        model=(app_settings.TOOLNET_MODEL or "").strip() or None,
    )


@router.post("/pipelines/{pipeline_id}/ai-settings/preview")
async def preview_ai_settings(
    pipeline_id: str,
    body: AiSettingsPreviewRequest,
    _: None = Depends(require_admin),
) -> dict:
    pipeline = await pipelines.get_pipeline(pipeline_id)
    if pipeline is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found.")

    sample_title = body.sample_title
    sample_desc = body.sample_description
    sample_tags = body.sample_hashtags
    sample_url = body.sample_source_url

    if not sample_title or sample_desc is None or sample_tags is None:
        sample_row = await ai_repo.get_sample_for_pipeline(pipeline_id)
        if sample_row:
            sample_title = sample_title or sample_row.get("title") or "Mẫu video thực tế"
            sample_desc = sample_desc if sample_desc is not None else (sample_row.get("description") or "")
            sample_tags = sample_tags if sample_tags is not None else sample_row.get("hashtags", [])
            sample_url = sample_url or "https://facebook.com/reel/123456789"
        else:
            sample_title = sample_title or "Khám phá bí ẩn tự nhiên kỳ thú"
            sample_desc = sample_desc if sample_desc is not None else "Đoạn video ngắn ghi lại những hiện tượng thú vị trong đời sống tự nhiên."
            sample_tags = sample_tags if sample_tags is not None else ["#khampha", "#thiennhien", "#shorts"]
            sample_url = sample_url or "https://facebook.com/reel/123456789"

    final_title = apply_title_template(body.title_template, sample_title)
    final_hashtags = apply_locked_hashtags(body.locked_hashtags, sample_tags)
    final_desc = apply_description_template(
        body.description_template,
        sample_desc,
        final_hashtags,
        sample_url,
    )

    return {
        "ok": True,
        "sample_original": {
            "title": sample_title,
            "description": sample_desc,
            "hashtags": sample_tags,
            "source_url": sample_url,
        },
        "preview": {
            "title": final_title,
            "description": final_desc,
            "hashtags": final_hashtags,
        },
    }
