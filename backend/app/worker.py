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
from app.youtube import upload_video, YouTubeUploadRejected


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
    """Only requeue work that provably has not entered an external upload."""
    from app.upload_attempts import read_attempt, read_receipt

    def recover(db):
        jobs = list(db.scalars(select(VideoJob).where(
            VideoJob.status.in_(["downloading", "uploading", "upload_unknown"])
        )))
        for job in jobs:
            evidence = read_receipt(job.id) or read_attempt(db, job.id)
            if evidence and evidence.get("video_id"):
                _finalize_upload(db, job.id, evidence)
                continue
            pub = _find_linked_publication(db, job)
            if evidence or job.status in {"uploading", "upload_unknown"}:
                job.status = "upload_unknown"
                job.error = "UPLOAD_RECONCILIATION_REQUIRED: worker restarted during upload; no automatic reupload"
                if pub is not None and pub.status != "published":
                    pub.status = "failed"
                    pub.error = job.error
            else:
                job.status = "pending"
                job.error = "Recovered before upload after worker restart"
                if pub is not None and pub.status != "published":
                    pub.status = "queued"
                    pub.error = job.error
    try:
        _db(recover)
    except Exception:
        # A temporary outage must not abort application startup. Work remains
        # held in its original state until a subsequent recovery/reconciliation.
        logger.exception("Database unavailable during recovery; no jobs requeued")


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
            # A rescheduled publication holds its job pending until the new
            # slot is due. Never upload ahead of the publication schedule.
            linked_pub = _find_linked_publication(db, job)
            if linked_pub is not None and linked_pub.scheduled_at is not None:
                slot = linked_pub.scheduled_at
                if slot.tzinfo is None:
                    slot = slot.replace(tzinfo=timezone.utc)
                if slot > utcnow():
                    continue
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
    rejected_attempt: dict | None = None,
) -> None:
    error_text = str(error)

    if len(error_text) > 5000:
        error_text = (
            error_text[:5000]
        )

    def record_failure(db):
        message = error_text
        if rejected_attempt is not None:
            from app.upload_attempts import write_attempt
            write_attempt(db, job_id, rejected_attempt)
        job = db.get(
            VideoJob,
            job_id,
        )

        if job is None:
            return

        if is_quota_error(message) or message.startswith("UPLOAD_POLICY_WAIT:"):
            if is_quota_error(message):
                until = pause_after_quota_error(db, destination_id=job.destination_id if "uploadlimitexceeded" in message.lower() else None)
                message = f"YOUTUBE_QUOTA_EXHAUSTED until {until.isoformat()}: {message}"
            job.status = "pending"
            job.error = message
            pub = _find_linked_publication(db, job)
            _set_publication_status(db, pub, "scheduled", error=message)
            if job.destination_id:
                dest = db.get(Destination, job.destination_id)
                if dest:
                    dest.last_skip_reason = message
            return

        job.status = "failed"
        job.progress = 0
        job.error = message

        if "invalid_grant" in message.lower() and job.destination_id:
            destination = db.get(Destination, job.destination_id)
            if destination is not None:
                destination.connected = False
                destination.last_skip_reason = REASON_OAUTH_REAUTH
                logger.error(
                    "Destination %s YouTube OAuth refresh token is invalid; "
                    "reconnect required before further uploads",
                    destination.id,
                )

        pub = _find_linked_publication(db, job)
        _set_publication_status(db, pub, "failed", error=message)

    _db(record_failure)


def _db(operation):
    from app.db_retry import run_db
    return run_db(operation, session_factory=SessionLocal)


def _load_upload_context(db, job_id):
    job = db.get(VideoJob, job_id)
    if job is None:
        return None
    pub = _find_linked_publication(db, job)
    if pub is not None and not pub.external_post_id and not job.youtube_video_id:
        from app.upload_attempts import guard_retry
        guard_retry(db, pub, exclude_job_id=job.id)
    destination = db.get(Destination, job.destination_id) if job.destination_id else None
    if destination is None:
        candidates = list(db.scalars(select(Destination).where(
            Destination.pipeline_id == job.pipeline_id,
            Destination.platform == "youtube", Destination.enabled == True,
            Destination.connected == True,
        )))
        candidates = [dest for dest in candidates if dest.credentials]
        if len(candidates) != 1:
            raise RuntimeError("VideoJob thiếu destination_id; từ chối đoán credential")
        destination = candidates[0]
        job.destination_id = destination.id
    pipeline = db.get(Pipeline, job.pipeline_id) if job.pipeline_id else None
    from app.channel_dna import get_dna
    dna = get_dna(db, destination.id)
    locked = (dna.locked_hashtags or []) if dna is not None else []
    # Load all data before leaving the short transaction. No AI/HTTP in it.
    db.flush()
    for obj in (job, pub, destination, pipeline):
        if obj is not None:
            db.expunge(obj)
    return job, pub, destination, pipeline, locked


def _finalize_upload(db, job_id, receipt):
    from app.upload_attempts import write_attempt
    job = db.get(VideoJob, job_id)
    if job is None:
        raise RuntimeError("Upload receipt has no job; reconciliation required")
    video_id = receipt["video_id"]
    if job.youtube_video_id and job.youtube_video_id != video_id:
        raise RuntimeError("Conflicting YouTube IDs; manual reconciliation required")
    pub = _find_linked_publication(db, job)
    if pub and pub.external_post_id and pub.external_post_id != video_id:
        raise RuntimeError("Conflicting publication YouTube IDs")
    scheduled = receipt["publish_mode"] == "scheduled"
    outcome = "scheduled" if scheduled else "published"
    job.youtube_video_id = video_id
    job.youtube_url = f"https://youtu.be/{video_id}"
    job.status = outcome
    job.progress = 100
    job.error = None
    job.title = receipt["title"]
    job.description = receipt["description"]
    job.youtube_publish_mode = receipt["publish_mode"]
    job.youtube_scheduled = scheduled
    job.youtube_schedule_timezone = receipt["timezone"]
    publish_at = datetime.fromisoformat(receipt["publish_at"]) if receipt.get("publish_at") else None
    job.youtube_publish_at = publish_at
    if pub is not None:
        pub.status = outcome
        pub.error = None
        pub.external_post_id = video_id
        pub.external_url = job.youtube_url
        pub.title = job.title
        pub.description = job.description
        pub.youtube_publish_mode = job.youtube_publish_mode
        pub.youtube_privacy_status = receipt["privacy"]
        pub.youtube_scheduled = scheduled
        pub.youtube_schedule_timezone = receipt["timezone"]
        pub.youtube_publish_at = publish_at
        if scheduled:
            pub.scheduled_at = publish_at
        elif pub.published_at is None:
            pub.published_at = datetime.fromisoformat(receipt["received_at"])
    video = db.scalar(select(DouyinVideo).where(
        DouyinVideo.pipeline_id == job.pipeline_id,
        DouyinVideo.video_id == job.source_video_id,
    ).limit(1))
    if video is not None:
        video.status = outcome
        video.youtube_video_id = video_id
        video.youtube_url = job.youtube_url
        if scheduled:
            video.scheduled_at = publish_at
        elif video.published_at is None:
            video.published_at = datetime.fromisoformat(receipt["received_at"])
    write_attempt(db, job_id, {**receipt, "phase": "finalized"})


def process_job(job_id: str) -> None:
    from app.upload_attempts import (
        read_attempt, write_attempt, read_receipt, save_receipt,
        UploadReconciliationRequired,
    )
    from app.youtube_scheduling import MODE_TO_PRIVACY, parse_publish_at
    from app.youtube import _load_from_json
    phase = "before_upload"
    receipt = None
    try:
        previous = _db(lambda db: read_attempt(db, job_id))
        receipt = read_receipt(job_id)
        if receipt and receipt.get("video_id"):
            # DB-only recovery; absolutely no call to videos.insert.
            _db(lambda db: _finalize_upload(db, job_id, receipt))
            return
        if previous and previous.get("phase") != "rejected":
            if previous.get("video_id"):
                _db(lambda db: _finalize_upload(db, job_id, previous))
                return
            raise UploadReconciliationRequired("UPLOAD_RECONCILIATION_REQUIRED: previous upload outcome unknown")
        context = _db(lambda db: _load_upload_context(db, job_id))
        if context is None:
            return
        job, pub, destination, pipeline, locked = context
        if job.youtube_video_id or (pub and pub.external_post_id):
            logger.info("Job %s already has a YouTube ID; no upload", job_id)
            return
        if job.status in {"upload_unknown", "published", "scheduled"}:
            raise UploadReconciliationRequired("UPLOAD_RECONCILIATION_REQUIRED: job is not safe to upload")
        download = download_video(job.source_url, job_id, share_text=(
            job.description if is_raw_douyin_share_text(job.description) else None
        ))
        # Metadata generation can take minutes. All objects here are detached.
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
        description = repair_description(description, locked=locked)
        job.description = description
        valid, reason = validate_metadata(title, description, locked=locked)
        if not valid:
            raise RuntimeError(f"Metadata validation failed; upload blocked: {reason}")

        publish_mode = (getattr(job, "youtube_publish_mode", None) or "").lower() or None
        publish_at_utc = getattr(job, "youtube_publish_at", None)
        sched_tz = getattr(job, "youtube_schedule_timezone", None) or "Asia/Ho_Chi_Minh"
        if pub is not None:
            if not publish_mode or publish_mode == "immediate":
                _pm = (getattr(pub, "youtube_publish_mode", None) or "").lower()
                if _pm:
                    publish_mode = _pm
            if publish_at_utc is None:
                publish_at_utc = getattr(pub, "youtube_publish_at", None)
            if getattr(pub, "youtube_schedule_timezone", None):
                sched_tz = pub.youtube_schedule_timezone
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

        destination_id = destination.id
        raw_credentials = _db(lambda db: db.get(Destination, destination_id).credentials)
        # Credential refresh is HTTP too: do it outside the DB transaction.
        # The Google client can refresh its in-memory token during upload.
        credentials = _load_from_json(raw_credentials)
        evidence = {
            "phase": "upload_started", "title": title, "description": description,
            "publish_mode": publish_mode, "privacy": privacy_for_upload,
            "publish_at": publish_at_utc.isoformat() if publish_at_utc else None,
            "timezone": sched_tz, "destination_id": destination_id,
            "publication_id": job.publication_id,
        }

        def begin_upload(db):
            live = db.get(VideoJob, job_id)
            old = read_attempt(db, job_id)
            if old and old.get("phase") != "rejected":
                # An ambiguous commit may have stored this intent; never replay
                # the external effect, even if it means a conservative hold.
                raise UploadReconciliationRequired("UPLOAD_RECONCILIATION_REQUIRED: upload intent already exists")
            if live.status != "downloading":
                raise UploadReconciliationRequired("Job is no longer claimed for upload")
            dest = db.get(Destination, destination_id)
            reason = _upload_policy_block(db, dest, job_id)
            if reason:
                raise RuntimeError(f"UPLOAD_POLICY_WAIT: {reason}")
            live.title, live.description = title, description
            live.source_title = download.title
            live.status = "uploading"
            live.progress = 55
            linked = _find_linked_publication(db, live)
            if live.youtube_video_id or (linked is not None and linked.external_post_id):
                raise UploadReconciliationRequired("Publication already has a YouTube ID")
            _set_publication_status(db, linked, "uploading")
            write_attempt(db, job_id, evidence)
        _db(begin_upload)
        # Intent is committed BEFORE first request. DB no longer participates
        # in the network upload; a transient DB failure cannot restart it.
        phase = "during_upload"
        video_id = upload_video(
            db=None, credentials=credentials, file_path=download.file_path,
            title=title, description=description, privacy_status=privacy_for_upload,
            pipeline_id=job.pipeline_id, destination_id=destination_id,
            publish_at=publish_at_utc, publish_mode=publish_mode,
        )
        phase = "after_upload"
        receipt = {**evidence, "phase": "uploaded", "video_id": video_id,
                   "received_at": utcnow().isoformat()}
        logger.info("YOUTUBE_UPLOAD_RECEIVED job=%s video=%s", job_id, video_id)
        try:
            save_receipt(job_id, receipt)
        except Exception:
            # Still attempt the remote finalization using the in-memory ID.
            logger.exception("Upload receipt disk write failed job=%s video=%s", job_id, video_id)
        _db(lambda db: _finalize_upload(db, job_id, receipt))
        logger.info("Published job=%s video=%s", job_id, video_id)
    except Exception as exc:
        logger.exception("Job failed job=%s phase=%s video=%s", job_id, phase,
                         receipt.get("video_id") if receipt else None)
        if isinstance(exc, YouTubeUploadRejected) and is_quota_error(str(exc)):
            # A terminal quota rejection is positive evidence that no upload
            # completed. Preserve normal quota pausing, never treat transport
            # failures or lost responses as a confirmed rejection.
            try:
                mark_failed(job_id, exc, rejected_attempt={
                    **evidence, "phase": "rejected", "error": str(exc)[:2000],
                })
            except Exception:
                logger.exception("Cannot persist confirmed quota rejection job=%s; intent remains held", job_id)
        elif phase in {"during_upload", "after_upload"} or isinstance(exc, UploadReconciliationRequired):
            error = UploadReconciliationRequired(
                f"UPLOAD_RECONCILIATION_REQUIRED {phase}: {exc}"
            )
            # Best effort: preserve known ID even when finalization exhausted.
            def hold(db):
                live = db.get(VideoJob, job_id)
                if live is None or live.status == "published":
                    return
                if receipt:
                    live.youtube_video_id = receipt.get("video_id")
                    live.youtube_url = f"https://youtu.be/{receipt['video_id']}"
                    write_attempt(db, job_id, receipt)
                live.status = "upload_unknown"
                live.error = str(error)[:5000]
                linked = _find_linked_publication(db, live)
                if linked is not None and linked.status != "published":
                    linked.status = "failed"
                    linked.error = live.error
                    if receipt:
                        linked.external_post_id = receipt["video_id"]
                        linked.external_url = live.youtube_url
            try:
                _db(hold)
            except Exception:
                logger.exception("Cannot persist upload hold job=%s; remote intent prevents reupload", job_id)
        else:
            try:
                mark_failed(job_id, exc if str(exc).startswith("UPLOAD_POLICY_WAIT:") or is_quota_error(str(exc))
                            else RuntimeError(f"BEFORE_UPLOAD: {exc}"))
            except Exception:
                logger.exception("Cannot persist failure job=%s; worker continues", job_id)
    finally:
        cleanup_job_files(job_id)


def reconcile_known_uploads() -> None:
    """Repair DB state from a trusted receipt; never initiate an upload."""
    from app.upload_attempts import read_attempt, read_receipt
    def reconcile(db):
        rows = db.scalars(select(VideoJob).where(
            VideoJob.status.in_(["uploading", "upload_unknown"])
        ))
        for job in rows:
            evidence = read_receipt(job.id) or read_attempt(db, job.id)
            if evidence and evidence.get("video_id"):
                _finalize_upload(db, job.id, evidence)
    _db(reconcile)


async def worker_loop() -> None:
    logger.info(
        "Background worker started"
    )

    while True:
        try:
            await asyncio.to_thread(reconcile_known_uploads)
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
