import asyncio
import logging
import re

from sqlalchemy import select, update

from app.config import settings
from app.ai_metadata import generate_youtube_metadata
from app.db import SessionLocal
from app.douyin import (
    cleanup_job_files,
    download_video,
)
from app.models import VideoJob
from app.youtube import upload_video


logger = logging.getLogger(
    "douyin-youtube-worker"
)


def is_raw_douyin_share_text(text: str | None) -> bool:
    if not text:
        return False
    return (
        "复制打开抖音" in text
        or "v.douyin.com" in text.lower()
        or "看看" in text
        or "的作品" in text
        or re.match(r"^\d+\.\d+\s+复制打开抖音", text) is not None
    )


def validate_final_description(text: str) -> bool:
    lowered = text.lower()
    if "v.douyin.com" in lowered:
        return False
    if "douyin.com" in lowered:
        return False
    if "复制打开抖音" in text:
        return False
    if "https://" in lowered or "http://" in lowered:
        return False
    return True


def validate_hashtags(text: str) -> bool:
    tags = re.findall(r"#\w+", text)
    if len(tags) != 5:
        return False
    if len(set(tags)) != 5:
        return False
    lowered_text = text.lower()
    for tag in tags:
        tag_lower = tag.lower()
        if "http" in tag_lower:
            return False
        if "douyin" in tag_lower:
            return False
        if "tiktok" in tag_lower:
            return False
    return True


def recover_incomplete_jobs() -> None:
    with SessionLocal.begin() as db:
        db.execute(
            update(VideoJob)
            .where(
                VideoJob.status.in_(
                    [
                        "downloading",
                        "uploading",
                    ]
                )
            )
            .values(
                status="pending",
                error=(
                    "Recovered after worker restart"
                ),
            )
        )


def claim_job() -> str | None:
    with SessionLocal.begin() as db:
        statement = (
            select(VideoJob)
            .where(
                VideoJob.status
                == "pending"
            )
            .order_by(
                VideoJob.created_at.asc()
            )
            .limit(1)
            .with_for_update(
                skip_locked=True
            )
        )

        job = (
            db.execute(statement)
            .scalars()
            .first()
        )

        if job is None:
            return None

        job.status = "downloading"
        job.progress = 10
        job.error = None
        job.attempts += 1

        return job.id


def mark_failed(
    job_id: str,
    error: Exception,
) -> None:
    error_text = str(error)

    if len(error_text) > 5000:
        error_text = (
            error_text[:5000]
        )

    with SessionLocal.begin() as db:
        job = db.get(
            VideoJob,
            job_id,
        )

        if job is None:
            return

        job.status = "failed"
        job.progress = 0
        job.error = error_text


def process_job(
    job_id: str,
) -> None:
    try:
        with SessionLocal() as db:
            job = db.get(
                VideoJob,
                job_id,
            )

            if job is None:
                return

            source_url = (
                job.source_url
            )

        download = download_video(
            source_url,
            job_id,
            share_text=(
                job.description
                if is_raw_douyin_share_text(
                    job.description
                )
                else None
            ),
        )

        with SessionLocal.begin() as db:
            job = db.get(
                VideoJob,
                job_id,
            )

            if job is None:
                return

            job.source_title = (
                download.title
            )

            job.status = "uploading"
            job.progress = 55
            
        with SessionLocal.begin() as db:
            job = db.get(
                VideoJob,
                job_id,
            )
            
            if job is None:
                return

            fallback_title = (
                download.title
                or job.source_title
                or ""
            )

            source_context = (
                download.source_context.strip()
                or fallback_title
            )

            original_share_text = (
                job.description
                if is_raw_douyin_share_text(
                    job.description
                )
                else None
            )

            if original_share_text:
                source_context = (
                    original_share_text
                    + "\n\n"
                    + "Rcuts metadata:\n"
                    + source_context
                )
            elif source_context != fallback_title:
                source_context = (
                    fallback_title
                    + "\n\n"
                    + "Rcuts metadata:\n"
                    + source_context
                )

            logger.info(
                "Downloaded job=%s parser=%s title=%r",
                job_id,
                download.parser_name,
                download.title,
            )

            title = job.title
            description = job.description

            has_raw_context = is_raw_douyin_share_text(
                description
            )
            needs_ai = (
                not title
                or not description
                or has_raw_context
            )

            if needs_ai:
                if description:
                    source_context = (
                        description
                        + "\n\n"
                        + source_context
                    )

                logger.info(
                    "Generating AI metadata for job %s using context",
                    job_id,
                )
                ai_result = generate_youtube_metadata(
                    source_context
                )
                if not ai_result:
                    raise RuntimeError(
                        "AI metadata generation failed"
                    )

                ai_title, ai_desc = ai_result
                if not title:
                    title = ai_title
                if not description or has_raw_context:
                    description = ai_desc

                job.title = title
                job.description = description

            title = title.strip()

            invalid_titles = {
                "",
                "douyin video",
                "short video",
                "video",
                "untitled"
            }

            if title.lower() in invalid_titles:
                raise RuntimeError(
                    "AI metadata/title generation failed; upload blocked"
                )

            if not validate_final_description(description):
                logger.warning(
                    "First-pass description validation failed for job %s, retrying AI once",
                    job_id,
                )
                ai_result = generate_youtube_metadata(
                    source_context
                )
                if not ai_result:
                    raise RuntimeError(
                        "AI metadata generation failed on retry; upload blocked"
                    )

                retry_title, retry_desc = ai_result
                if not validate_final_description(retry_desc):
                    raise RuntimeError(
                        "AI description validation failed after retry; upload blocked"
                    )

                title = retry_title or title
                description = retry_desc
                job.title = title
                job.description = description

            if not validate_hashtags(description):
                logger.warning(
                    "First-pass hashtag validation failed for job %s, retrying AI once",
                    job_id,
                )
                ai_result = generate_youtube_metadata(
                    source_context
                )
                if not ai_result:
                    raise RuntimeError(
                        "AI metadata generation failed on retry; upload blocked"
                    )

                retry_title, retry_desc = ai_result
                if not validate_hashtags(retry_desc):
                    raise RuntimeError(
                        "AI hashtags validation failed after retry; upload blocked"
                    )

                title = retry_title or title
                description = retry_desc
                job.title = title
                job.description = description

            video_id = upload_video(
                db=db,
                file_path=(
                    download.file_path
                ),
                title=title,
                description=description,
                privacy_status=(
                    job.privacy_status
                ),
            )

        with SessionLocal.begin() as db:
            job = db.get(
                VideoJob,
                job_id,
            )

            if job is None:
                return

            job.youtube_video_id = (
                video_id
            )

            job.youtube_url = (
                "https://youtu.be/"
                + video_id
            )

            job.status = "published"
            job.progress = 100
            job.error = None

        logger.info(
            "Published job=%s video=%s",
            job_id,
            video_id,
        )

    except Exception as exc:
        logger.exception(
            "Job failed: %s",
            job_id,
        )

        mark_failed(
            job_id,
            exc,
        )

    finally:
        cleanup_job_files(
            job_id
        )


async def worker_loop() -> None:
    logger.info(
        "Background worker started"
    )

    while True:
        try:
            job_id = await asyncio.to_thread(
                claim_job
            )

            if not job_id:
                await asyncio.sleep(
                    settings.worker_poll_seconds
                )
                continue

            await asyncio.to_thread(
                process_job,
                job_id,
            )

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception(
                "Worker loop error"
            )

            await asyncio.sleep(
                settings.worker_poll_seconds
            )
