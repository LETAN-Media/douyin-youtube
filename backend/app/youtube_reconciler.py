"""Reconciler for native YouTube scheduled publishing.

Polls scheduled rows where youtube_publish_at <= now + window,
reads videos.list, and flips scheduled -> published when YouTube
reports public. Never re-uploads.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

logger = logging.getLogger("douyin-youtube-schedule-reconciler")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def reconcile_scheduled_videos(
    window_minutes: int = 15,
    limit: int = 50,
    db_session=None,
) -> dict:
    """Check due scheduled publications and update their state.

    Returns summary dict {checked, published, still_scheduled, errors}.
    """
    from app.db import SessionLocal
    from app.models import Publication

    close = False
    if db_session is None:
        db_session = SessionLocal()
        close = True
    try:
        return _reconcile(db_session, window_minutes=window_minutes, limit=limit)
    finally:
        if close:
            try:
                db_session.close()
            except Exception:
                pass


def _reconcile(db, window_minutes: int, limit: int) -> dict:
    from app.models import Publication
    from app.youtube import get_video_status

    now = _utcnow()
    horizon = now + timedelta(minutes=max(0, window_minutes))
    rows = list(
        db.execute(
            select(Publication)
            .where(Publication.youtube_scheduled == True)  # noqa: E712
            .where(Publication.status == "scheduled")
            .where(Publication.youtube_publish_at.is_not(None))
            .where(Publication.youtube_publish_at <= horizon)
            .order_by(Publication.youtube_publish_at.asc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    summary = {"checked": len(rows), "published": 0, "still_scheduled": 0, "errors": 0}
    for pub in rows:
        video_id = pub.external_post_id
        if not video_id:
            continue
        try:
            info = get_video_status(db, pub.destination_id, video_id)
        except Exception as exc:
            pub.error = str(exc)[:2000]
            summary["errors"] += 1
            continue
        privacy = (info.get("privacyStatus") or "").lower()
        published_at = info.get("publishedAt")
        if privacy == "public":
            pub.status = "published"
            pub.youtube_scheduled = False
            try:
                if published_at:
                    dt = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
                    pub.youtube_actual_published_at = dt.astimezone(timezone.utc)
                    pub.published_at = dt.astimezone(timezone.utc)
                else:
                    pub.youtube_actual_published_at = now
                    pub.published_at = now
            except Exception:
                pub.youtube_actual_published_at = now
                pub.published_at = now
            pub.error = None
            summary["published"] += 1
            # Mirror to DouyinVideo + VideoJob for consistency.
            try:
                from app.models import DouyinVideo, VideoJob

                video = db.get(DouyinVideo, pub.douyin_video_id)
                if video is not None:
                    video.status = "published"
                    video.published_at = pub.published_at or now
                jobs = list(
                    db.execute(
                        select(VideoJob).where(VideoJob.publication_id == pub.id)
                    )
                    .scalars()
                    .all()
                )
                for j in jobs:
                    j.status = "published"
                    j.youtube_actual_published_at = pub.youtube_actual_published_at
                    j.error = None
            except Exception:
                logger.exception("reconcile mirror failed pub=%s", pub.id)
        else:
            summary["still_scheduled"] += 1
    try:
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
    return summary
