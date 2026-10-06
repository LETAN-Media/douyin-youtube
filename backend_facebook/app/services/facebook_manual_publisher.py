"""Manual Facebook -> YouTube publishing.

Business flow is fully independent from auto (no inventory, no scheduler,
no reels rows, no AI-worker writes). Shares with auto ONLY the heavy
resources under the single publisher-loop semaphore (concurrency 1):
destination credentials, FastSaver, ToolNet, the YouTube uploader.
"""

import asyncio
import logging
import time
from typing import Any

import httpx

from ..db.repositories import ai_settings as ai_settings_repo
from ..db.repositories import destinations, manual_publications as manual_repo
from .facebook_ai_metadata import (
    FacebookMetadataGenerator,
    MetadataError,
    apply_description_template,
    apply_locked_hashtags,
    apply_title_template,
)
from .facebook_media import (
    cleanup_job_dir,
    job_dir,
    sanitize_job_id,
)
from .facebook_manual_media import (
    ManualResolverError,
    download_manual_media,
    resolve_manual_media,
)
from .facebook_youtube_publisher import (
    YouTubePublisherError,
    load_destination_credentials_async,
    refresh_if_needed,
    upload_video,
    validate_publish_at,
    validate_visibility,
)

logger = logging.getLogger(__name__)

MANUAL_JOB_TMP_PREFIX = "manual_"

ERROR_CODES = {
    "DESTINATION_NOT_FOUND",
    "DESTINATION_NOT_CONNECTED",
    "YOUTUBE_AUTH_FAILED",
    "INVALID_VISIBILITY",
    "INVALID_PUBLISH_AT",
    "SLOT_MISSED",
    "MEDIA_RESOLVE_FAILED",
    "MEDIA_DOWNLOAD_FAILED",
    "MANUAL_METADATA_INVALID",
    "TOOLNET_UNAVAILABLE",
    "DUPLICATE_VIDEO",
    "UNEXPECTED",
}


async def generate_manual_metadata(
    *,
    pipeline_id: str | None,
    caption: str | None,
    source_url: str | None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """AI title/description/hashtags for a manual publish. No DB writes.

    Uses the owning pipeline's AI settings (templates, locked tags,
    language, system prompt) exactly like the auto path. Raises
    MetadataError (typed) when ToolNet is unavailable or output invalid.
    """
    if pipeline_id:
        pipeline_settings, _ = await ai_settings_repo.current_config_hash(pipeline_id)
    else:
        pipeline_settings = ai_settings_repo.default_settings("manual")
    if not pipeline_settings.get("enabled", True):
        raise MetadataError(
            "AI_DISABLED_FOR_PIPELINE",
            "AI is disabled for this pipeline. Enable it or type metadata manually.",
        )
    generator = FacebookMetadataGenerator.from_settings(
        transport=transport, model=pipeline_settings.get("model")
    )
    generator.custom_system_prompt = pipeline_settings.get("system_prompt") or ""
    generator.language = pipeline_settings.get("language") or "vi"
    generated = await generator.generate(
        f"manual-{(source_url or '')[-12:]}" or "manual",
        caption,
        source_url,
    )
    title = apply_title_template(pipeline_settings.get("title_template"), generated.title)
    hashtags = apply_locked_hashtags(
        pipeline_settings.get("locked_hashtags"), generated.hashtags
    )
    description = apply_description_template(
        pipeline_settings.get("description_template"),
        generated.description,
        hashtags,
        source_url,
    )
    return {
        "title": title,
        "description": description,
        "hashtags": hashtags,
        "model": generated.model,
    }


async def _fail_manual(
    manual_id: str, error_code: str, error: str, **extra: Any
) -> dict[str, Any]:
    await manual_repo.mark_failed(manual_id, error_code, f"{error_code}: {error}")
    return {
        "manual_id": manual_id,
        "result": "failed",
        "error_code": error_code,
        "error": error,
        **extra,
    }


async def process_manual_job(
    job: dict[str, Any],
    transport: httpx.AsyncBaseTransport | None = None,
    youtube_factory=None,
) -> dict[str, Any]:
    """Run one claimed manual job: resolve -> download -> upload -> cleanup.

    Never persists FastSaver download URLs. Always cleans /tmp in finally.
    Returns a result dict with a typed error_code on failure.
    """
    manual_id = job["id"]
    destination_id = job["destination_id"]
    source_url = job["source_url"]
    started = time.monotonic()
    job_tmp_id = f"{MANUAL_JOB_TMP_PREFIX}{sanitize_job_id(manual_id)}"
    target_dir = job_dir(job_tmp_id)

    async def stage(name: str) -> None:
        try:
            await manual_repo.set_stage(manual_id, name)
        except Exception:
            pass

    try:
        destination = await destinations.get_destination(destination_id)
        if destination is None:
            return await _fail_manual(manual_id, "DESTINATION_NOT_FOUND", "Destination not found.")
        if not destination.get("connected") or not destination.get("channel_id"):
            return await _fail_manual(
                manual_id, "DESTINATION_NOT_CONNECTED",
                "YouTube channel is not connected. Reconnect it first.",
            )
        try:
            visibility = validate_visibility(job.get("visibility") or "public")
        except YouTubePublisherError as exc:
            return await _fail_manual(manual_id, "INVALID_VISIBILITY", str(exc))

        publish_at_raw = job.get("publish_at")
        try:
            validated_publish_at = (
                validate_publish_at(publish_at_raw) if publish_at_raw else None
            )
        except YouTubePublisherError as exc:
            return await _fail_manual(manual_id, "SLOT_MISSED", str(exc))

        title = (job.get("youtube_title") or "").strip()
        if not title:
            return await _fail_manual(
                manual_id, "MANUAL_METADATA_INVALID", "Title must not be empty."
            )
        title = title[:100]
        description = (job.get("youtube_description") or "")[:5000]

        await stage("resolving")
        try:
            # Fresh resolve right before download: direct URLs may expire,
            # so the preview-time URL is never persisted or reused.
            media = await resolve_manual_media(source_url, transport=transport)
        except ManualResolverError as exc:
            return await _fail_manual(manual_id, exc.code, str(exc))

        await stage("downloading")
        try:
            output = await download_manual_media(media, job_tmp_id, transport=transport)
            file_bytes = output.stat().st_size
            if file_bytes <= 0:
                raise ManualResolverError("empty", "Downloaded file is empty.")
        except ManualResolverError as exc:
            code = exc.code if exc.code != "empty" else "MANUAL_DOWNLOAD_FAILED"
            return await _fail_manual(manual_id, code, str(exc))

        await stage("uploading")
        try:
            credentials = await load_destination_credentials_async(destination_id)
            credentials = await refresh_if_needed(destination_id, credentials)
        except Exception as exc:
            return await _fail_manual(
                manual_id, "YOUTUBE_AUTH_FAILED",
                f"Could not load YouTube credentials for this channel: {type(exc).__name__}",
            )

        try:
            youtube_video_id = await asyncio.to_thread(
                upload_video,
                credentials, output, title, description, visibility,
                publish_at=validated_publish_at,
                youtube_factory=youtube_factory,
            )
        except YouTubePublisherError as exc:
            return await _fail_manual(manual_id, exc.code, str(exc))
        except Exception as exc:
            return await _fail_manual(
                manual_id, "UNEXPECTED", f"{type(exc).__name__}: {exc}"
            )

        await stage("completing")
        if validated_publish_at:
            await manual_repo.mark_scheduled(manual_id, youtube_video_id)
            result = "scheduled"
        else:
            # Immediate mode uploads public (default) — visible right away.
            await manual_repo.mark_published(manual_id, youtube_video_id)
            result = "published"
        logger.info("manual publish %s -> %s (%s)", manual_id, youtube_video_id, result)
        return {
            "manual_id": manual_id,
            "result": result,
            "youtube_video_id": youtube_video_id,
            "elapsed_s": time.monotonic() - started,
        }
    finally:
        try:
            cleanup_job_dir(target_dir)
        except Exception:
            pass


async def handle_unexpected_manual_error(job: dict[str, Any], exc: BaseException) -> None:
    """Last resort: never leave a manual job stuck in processing."""
    logger.exception("unexpected error processing manual job %s: %s", job.get("id"), exc)
    try:
        await manual_repo.mark_failed(
            job["id"], "UNEXPECTED", f"UNEXPECTED: {type(exc).__name__}: {exc}"
        )
    except Exception:
        logger.exception("failed to mark manual job %s failed", job.get("id"))
    try:
        cleanup_job_dir(target_dir)
    except Exception:
        pass
