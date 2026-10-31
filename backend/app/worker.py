import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update, func

from app.config import settings
from app.schedule_policy import effective_schedule, ScheduleError
from app.upload_quota import quota_block_reason, is_quota_error, pause_after_quota_error
from app.hashtag_policy import (
    validate_hashtags, repair_description,
    validate_metadata,
)
from app.ai_metadata import generate_youtube_metadata
from app.db import SessionLocal
from app.douyin import (
    cleanup_job_files,
    download_video,
)
from app.models import Destination, DouyinVideo, Pipeline, Publication, VideoJob
from app.scheduler import REASON_OAUTH_REAUTH
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


def _upload_policy_block(db, destination, job_id=None):
    from app.scheduler import count_published_day, destination_today
    reason = quota_block_reason(db, include_pending=False, exclude_job_id=job_id, destination_id=destination.id)
    if reason:
        return reason
    schedule = effective_schedule(destination)
    now = utcnow()
    published = count_published_day(db, destination, destination_today(destination, now))
    active = select(func.count(VideoJob.id)).where(
        VideoJob.destination_id == destination.id,
        VideoJob.status.in_(["downloading", "uploading"]),
    )
    if job_id:
        active = active.where(VideoJob.id != job_id)
    if published + (db.scalar(active) or 0) >= schedule.daily_upload_limit:
        return "DAILY_LIMIT_REACHED"
    latest = db.scalar(select(func.max(Publication.published_at)).where(
        Publication.destination_id == destination.id, Publication.status == "published"))
    if latest:
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        if (now-latest).total_seconds() < schedule.min_upload_interval_minutes * 60:
            return "UPLOAD_INTERVAL_WAIT"
    # Serialize uploads to one destination even when multiple workers run.
    if db.scalar(active):
        return "DESTINATION_UPLOAD_IN_PROGRESS"
    return None


def claim_job() -> str | None:
    with SessionLocal.begin() as db:
        # One oldest pending job per destination avoids a blocked channel
        # starving every other pipeline after a restart.
        ranked = select(VideoJob.id.label("id"), func.row_number().over(
            partition_by=VideoJob.destination_id,
            order_by=(VideoJob.created_at.asc(), VideoJob.id.asc()),
        ).label("rank")).where(VideoJob.status == "pending").subquery()
        candidates = db.scalars(select(VideoJob).where(VideoJob.id.in_(
            select(ranked.c.id).where(ranked.c.rank == 1)))
            .order_by(VideoJob.created_at.asc()).limit(100).with_for_update(skip_locked=True)).all()
        for job in candidates:
            if job.destination_id:
                from app.scheduler import locked_destination
                destination = locked_destination(db, job.destination_id)
                if destination:
                    try:
                        reason = _upload_policy_block(db, destination)
                    except ScheduleError as exc:
                        reason = f"INVALID_SCHEDULE: {exc}"
                    if reason:
                        destination.last_skip_reason = reason
                        continue
            changed = db.execute(update(VideoJob).where(VideoJob.id == job.id, VideoJob.status == "pending")
                .values(status="downloading", progress=10, error=None, attempts=VideoJob.attempts+1))
            if changed.rowcount != 1:
                continue
            pub = _find_linked_publication(db, job)
            _set_publication_status(db, pub, "downloading")
            return job.id
    return None


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

        if is_quota_error(error_text) or error_text.startswith("UPLOAD_POLICY_WAIT:"):
            if is_quota_error(error_text):
                until = pause_after_quota_error(db, destination_id=job.destination_id if "uploadlimitexceeded" in error_text.lower() else None)
                error_text = f"YOUTUBE_QUOTA_EXHAUSTED until {until.isoformat()}: {error_text}"
            job.status = "pending"
            job.error = error_text
            pub = _find_linked_publication(db, job)
            _set_publication_status(db, pub, "scheduled", error=error_text)
            if job.destination_id:
                dest = db.get(Destination, job.destination_id)
                if dest:
                    dest.last_skip_reason = error_text
            return

        job.status = "failed"
        job.progress = 0
        job.error = error_text

        if "invalid_grant" in error_text.lower() and job.destination_id:
            destination = db.get(Destination, job.destination_id)
            if destination is not None:
                destination.connected = False
                destination.last_skip_reason = REASON_OAUTH_REAUTH
                logger.error(
                    "Destination %s YouTube OAuth refresh token is invalid; "
                    "reconnect required before further uploads",
                    destination.id,
                )

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

            # Only DNA locks are mandatory. Pipeline lists are reference data.
            locked = []
            if destination is not None:
                from app.channel_dna import get_dna
                dna = get_dna(db, destination.id)
                locked = (dna.locked_hashtags or []) if dna is not None else []
            description = repair_description(description, locked=locked)
            job.description = description
            valid, reason = validate_metadata(title, description, locked=locked)
            if not valid:
                raise RuntimeError(f"Metadata validation failed; upload blocked: {reason}")

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

            # Resolve native scheduling intent: job fields win, else linked
            # Publication, else infer from legacy privacy_status.
            from app.youtube_scheduling import (
                MODE_TO_PRIVACY,
                normalize_youtube_error,
                parse_publish_at,
            )

            _pub_for_upload = _find_linked_publication(db, job)
            publish_mode = (getattr(job, "youtube_publish_mode", None) or "").lower() or None
            publish_at_utc = getattr(job, "youtube_publish_at", None)
            sched_tz = getattr(job, "youtube_schedule_timezone", None) or "Asia/Ho_Chi_Minh"
            if _pub_for_upload is not None:
                if not publish_mode or publish_mode == "immediate":
                    _pm = (getattr(_pub_for_upload, "youtube_publish_mode", None) or "").lower()
                    if _pm:
                        publish_mode = _pm
                if publish_at_utc is None:
                    publish_at_utc = getattr(_pub_for_upload, "youtube_publish_at", None)
                if getattr(_pub_for_upload, "youtube_schedule_timezone", None):
                    sched_tz = _pub_for_upload.youtube_schedule_timezone
            if not publish_mode:
                priv_lower = (job.privacy_status or "public").lower()
                publish_mode = {"public": "immediate", "private": "private", "unlisted": "unlisted"}.get(
                    priv_lower, "immediate"
                )
            if isinstance(publish_at_utc, str):
                try:
                    publish_at_utc = parse_publish_at(publish_at_utc)
                except Exception:
                    publish_at_utc = None
            # Ensure naive datetimes from SQLite are treated as UTC.
            if publish_at_utc is not None and getattr(publish_at_utc, "tzinfo", None) is None:
                publish_at_utc = publish_at_utc.replace(tzinfo=timezone.utc)
            privacy_for_upload = MODE_TO_PRIVACY.get(publish_mode, "public")

            # Layer C Dedup: check if job or publication already has youtube_video_id
            existing_yt_id = getattr(job, "youtube_video_id", None)
            if not existing_yt_id and _pub_for_upload is not None:
                existing_yt_id = getattr(_pub_for_upload, "external_post_id", None)

            if not existing_yt_id:
                live_destination = db.get(Destination, destination_id)
                if live_destination is not None:
                    db.refresh(live_destination)
                    reason = _upload_policy_block(db, live_destination, job_id)
                    if reason:
                        raise RuntimeError(f"UPLOAD_POLICY_WAIT: {reason}")

            try:
                if existing_yt_id:
                    logger.info(
                        "Job %s already has youtube_video_id=%s; skipping re-upload to YouTube",
                        job_id,
                        existing_yt_id,
                    )
                    video_id = existing_yt_id
                else:
                    video_id = upload_video(
                        db=db,
                        file_path=(
                            download.file_path
                        ),
                        title=title,
                        description=description,
                        privacy_status=privacy_for_upload,
                        pipeline_id=job.pipeline_id,
                        destination_id=destination_id,
                        publish_at=publish_at_utc,
                        publish_mode=publish_mode,
                    )
            except Exception as exc:
                # Store exact normalized YouTube error (invalidPublishAt etc.)
                try:
                    norm = normalize_youtube_error(exc)
                    job.error = norm[:5000]
                    _pub_err = _find_linked_publication(db, job)
                    if _pub_err is not None:
                        _pub_err.error = norm[:5000]
                except Exception:
                    pass
                raise

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

            # Native scheduling outcome: scheduled stays scheduled,
            # everything else is published immediately (incl. private/unlisted).
            is_scheduled = (publish_mode == "scheduled")
            if is_scheduled:
                job.status = "scheduled"
                job.youtube_scheduled = True
                job.youtube_publish_at = publish_at_utc
                try:
                    job.youtube_schedule_timezone = sched_tz
                except Exception:
                    pass
                job.youtube_publish_mode = "scheduled"
            else:
                job.status = "published"
                job.youtube_scheduled = False
                job.youtube_publish_mode = publish_mode
                try:
                    if publish_at_utc is not None:
                        job.youtube_publish_at = publish_at_utc
                except Exception:
                    pass
            job.progress = 100
            job.error = None

            try:
                pub = _find_linked_publication(db, job)
                if is_scheduled:
                    _set_publication_status(
                        db,
                        pub,
                        "scheduled",
                        external_post_id=video_id,
                        external_url=f"https://youtu.be/{video_id}",
                    )
                else:
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
                    try:
                        pub.youtube_publish_mode = publish_mode
                        pub.youtube_privacy_status = privacy_for_upload
                        pub.youtube_schedule_timezone = sched_tz
                        if is_scheduled:
                            pub.youtube_publish_at = publish_at_utc
                            pub.youtube_scheduled = True
                            pub.scheduled_at = publish_at_utc
                        else:
                            pub.youtube_scheduled = False
                            if publish_at_utc is not None:
                                pub.youtube_publish_at = publish_at_utc
                    except Exception:
                        pass
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
                if is_scheduled:
                    video.status = "scheduled"
                    video.scheduled_at = publish_at_utc or utcnow()
                else:
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
