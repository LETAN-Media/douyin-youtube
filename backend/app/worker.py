import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update

from app.config import settings
from app.ai_metadata import generate_youtube_metadata
from app.db import SessionLocal
from app.douyin import (
    cleanup_job_files,
    download_video,
)
from app.models import DouyinVideo, Pipeline, Publication, VideoJob
from app.youtube import upload_video


logger = logging.getLogger(
    "douyin-youtube-worker"
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


def validate_hashtags(
    text: str,
    pipeline: Pipeline | None = None,
) -> bool:
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

    if pipeline is None:
        return True

    fixed_hashtags = [
        tag.lower()
        for tag in (pipeline.fixed_hashtags or [])
    ]
    adaptive_hashtags = [
        tag.lower()
        for tag in (pipeline.adaptive_hashtags or [])
    ]
    allowed_hashtags = set(fixed_hashtags) | set(adaptive_hashtags)

    if not allowed_hashtags:
        return True

    tags_lower = [tag.lower() for tag in tags]

    fixed_required = sum(1 for tag in tags_lower if tag in fixed_hashtags)
    if fixed_required < len(fixed_hashtags):
        return False

    niche_count = sum(1 for tag in tags_lower if tag in allowed_hashtags)
    if niche_count < 3:
        return False

    return True


def _find_linked_publication(db, job: VideoJob) -> Publication | None:
    """Resolve Job -> Publication via publication_id (preferred).

    Never guess by bare video_id when multiple destinations exist:
    fallback always scopes by destination_id.
    """
    if getattr(job, "publication_id", None):
        pub = db.get(Publication, job.publication_id)
        if pub is not None:
            return pub
    if job.destination_id and job.source_video_id and job.pipeline_id:
        video = db.execute(
            select(DouyinVideo)
            .where(DouyinVideo.pipeline_id == job.pipeline_id)
            .where(DouyinVideo.video_id == job.source_video_id)
            .limit(1)
        ).scalar_one_or_none()
        if video is not None:
            pub = db.execute(
                select(Publication)
                .where(Publication.douyin_video_id == video.id)
                .where(
                    Publication.destination_id == job.destination_id
                )
                .order_by(Publication.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if pub is not None:
                # Backfill link for legacy jobs.
                try:
                    job.publication_id = pub.id
                except Exception:
                    pass
                return pub
    return None


def _set_publication_status(
    db,
    publication: Publication | None,
    status: str,
    error: str | None = None,
    external_post_id: str | None = None,
    external_url: str | None = None,
) -> None:
    if publication is None:
        return
    publication.status = status
    if status in ("downloading", "ai_metadata", "uploading", "processing"):
        if publication.started_at is None:
            publication.started_at = utcnow()
        try:
            publication.attempts = int(publication.attempts or 0) + 1
        except Exception:
            pass
    if error is not None:
        publication.error = error[:5000] if len(error) > 5000 else error
    elif status == "published":
        publication.error = None
    if external_post_id is not None:
        publication.external_post_id = external_post_id
    if external_url is not None:
        publication.external_url = external_url
    if status == "published":
        publication.published_at = utcnow()


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

        # Publications stuck in processing states go back to queued so the
        # scheduler/worker can continue after a Render restart.
        try:
            db.execute(
                update(Publication)
                .where(
                    Publication.status.in_(
                        [
                            "downloading",
                            "ai_metadata",
                            "uploading",
                            "processing",
                        ]
                    )
                )
                .values(
                    status="queued",
                    error="Recovered after worker restart",
                )
            )
        except Exception:
            logger.exception("Failed to recover publications")

        scheduled_videos = db.execute(
            select(DouyinVideo)
            .where(DouyinVideo.status == "scheduled")
        ).scalars().all()

        for video in scheduled_videos:
            job = db.execute(
                select(VideoJob)
                .where(VideoJob.pipeline_id == video.pipeline_id)
                .where(VideoJob.source_video_id == video.video_id)
                .limit(1)
            ).scalar_one_or_none()

            if job is None or job.status in ("published", "failed"):
                video.status = "backlog" if video.is_backlog else "new"
                video.scheduled_at = None


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

        # Mirror state to Publication: scheduled/queued -> downloading.
        try:
            pub = _find_linked_publication(db, job)
            _set_publication_status(db, pub, "downloading")
        except Exception:
            logger.exception("Failed to update publication on claim %s", job.id)

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

        try:
            pub = _find_linked_publication(db, job)
            _set_publication_status(db, pub, "failed", error=error_text)
        except Exception:
            logger.exception("Failed to update publication on job fail %s", job_id)


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

            try:
                pub = _find_linked_publication(db, job)
                _set_publication_status(db, pub, "ai_metadata")
            except Exception:
                logger.exception("Failed to set publication ai_metadata %s", job_id)
            
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

            pipeline = None
            if job.pipeline_id:
                with SessionLocal() as pipeline_db:
                    pipeline = pipeline_db.get(
                        Pipeline,
                        job.pipeline_id,
                    )

            destination = None
            if job.destination_id:
                from app.models import Destination as _Dest
                with SessionLocal() as dest_db:
                    destination = dest_db.get(
                        _Dest,
                        job.destination_id,
                    )

            pub = _find_linked_publication(db, job)
            is_manual = pub is not None and getattr(pub, "publication_mode", "auto") == "manual"

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
                    source_context,
                    pipeline=pipeline,
                    destination=destination,
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
                    source_context,
                    pipeline=pipeline,
                    destination=destination,
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

            # For manual mode, allow user-edited hashtags without strict pipeline whitelist check
            target_pipeline_for_tags = None if is_manual else pipeline
            if not validate_hashtags(description, pipeline=target_pipeline_for_tags):
                logger.warning(
                    "First-pass hashtag validation failed for job %s, retrying AI once",
                    job_id,
                )
                ai_result = generate_youtube_metadata(
                    source_context,
                    pipeline=pipeline,
                    destination=destination,
                )
                if not ai_result:
                    raise RuntimeError(
                        "AI metadata generation failed on retry; upload blocked"
                    )

                retry_title, retry_desc = ai_result
                if not validate_hashtags(retry_desc, pipeline=target_pipeline_for_tags):
                    raise RuntimeError(
                        "AI hashtags validation failed after retry; upload blocked"
                    )

                title = retry_title or title
                description = retry_desc
                job.title = title
                job.description = description

            try:
                _set_publication_status(db, pub, "uploading")
            except Exception:
                logger.exception("Failed to set publication uploading %s", job_id)

            # Destination OAuth isolation: always upload with the job's own
            # destination credentials, never pipeline/global fallback.
            destination_id = job.destination_id
            if not destination_id:
                # Legacy jobs created before multi-destination: resolve only
                # when the pipeline has exactly one connected YouTube
                # destination; otherwise refuse to guess between channels.
                from app.models import Destination as _Destination

                candidates = db.execute(
                    select(_Destination)
                    .where(_Destination.pipeline_id == job.pipeline_id)
                    .where(_Destination.platform == "youtube")
                    .where(_Destination.enabled == True)  # noqa: E712
                    .where(_Destination.connected == True)  # noqa: E712
                ).scalars().all()
                candidates = [
                    c for c in candidates if c.credentials
                ]
                if len(candidates) == 1:
                    destination_id = candidates[0].id
                    try:
                        job.destination_id = destination_id
                        pub0 = _find_linked_publication(db, job)
                        if pub0 is not None:
                            job.publication_id = pub0.id
                    except Exception:
                        pass
                else:
                    raise RuntimeError(
                        "VideoJob thiếu destination_id; "
                        "từ chối upload để tránh sai credential đa kênh"
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
                pipeline_id=job.pipeline_id,
                destination_id=destination_id,
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

            try:
                pub = _find_linked_publication(db, job)
                _set_publication_status(
                    db,
                    pub,
                    "published",
                    external_post_id=video_id,
                    external_url=f"https://youtu.be/{video_id}",
                )
                if pub is not None:
                    pub.title = job.title
                    pub.description = job.description
            except Exception:
                logger.exception(
                    "Failed to set publication published %s", job_id
                )

            video = db.execute(
                select(DouyinVideo)
                .where(DouyinVideo.pipeline_id == job.pipeline_id)
                .where(DouyinVideo.video_id == job.source_video_id)
                .limit(1)
            ).scalar_one_or_none()

            if video is not None:
                video.status = "published"
                video.published_at = utcnow()
                video.youtube_video_id = video_id
                video.youtube_url = f"https://youtu.be/{video_id}"

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
