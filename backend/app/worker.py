import asyncio
import logging

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
            
            title = job.title
            description = job.description
            
            if description and not title:
                # Use description as share_text context
                source_context = description + "\n\n" + source_context
            
            if not title or not description:
                logger.info("Generating AI metadata for job %s using context", job_id)
                ai_result = generate_youtube_metadata(source_context)
                if not ai_result:
                    raise RuntimeError("AI metadata generation failed")
                
                ai_title, ai_desc = ai_result
                if not title:
                    title = ai_title
                if not description:
                    description = ai_desc
                
                # Save to database so GET /api/jobs sees the real title
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
