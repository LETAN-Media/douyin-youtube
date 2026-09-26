import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import Destination, DouyinSource, DouyinVideo, Pipeline, Publication, VideoJob
from app.ai_metadata import evaluate_content_level


logger = logging.getLogger("douyin-youtube-scheduler")


# Scheduler skip-reason codes surfaced via scheduler-status for observability.
REASON_NOT_CONNECTED = "DESTINATION_NOT_CONNECTED"
REASON_NO_INVENTORY = "NO_AVAILABLE_INVENTORY"
REASON_DAILY_LIMIT = "DAILY_LIMIT_REACHED"
REASON_WAITING_SLOT = "WAITING_NEXT_SLOT"
REASON_DISABLED = "SCHEDULER_DISABLED"
REASON_WORKER_ERROR = "WORKER_ERROR"
REASON_UPLOAD_INTERVAL = "UPLOAD_INTERVAL_WAIT"
REASON_SOURCE_DAILY_LIMIT = "SOURCE_DAILY_LIMIT_REACHED"


def _keywords_hit(text: str, keywords: list[str] | None) -> bool:
    lowered = (text or "").lower()
    for kw in keywords or []:
        kw = (kw or "").strip().lower()
        if kw and kw in lowered:
            return True
    return False


def count_source_today(
    db: Session,
    source_id: str,
    day_start_utc: datetime,
) -> int:
    """AUTO publications (excl. failed/skipped) for a source since day start."""
    day_end = day_start_utc + timedelta(days=1)
    count = db.execute(
        select(func.count(Publication.id))
        .join(DouyinVideo, Publication.douyin_video_id == DouyinVideo.id)
        .where(DouyinVideo.source_id == source_id)
        .where(Publication.publication_mode == "auto")
        .where(Publication.created_at >= day_start_utc)
        .where(Publication.created_at < day_end)
        .where(Publication.status.notin_(["failed", "skipped"]))
    ).scalar_one_or_none()
    return int(count or 0)


def _source_daily_reached(
    db: Session,
    source: DouyinSource,
    day_start_utc: datetime,
) -> bool:
    try:
        limit = int(source.max_videos_per_day or 5)
    except (TypeError, ValueError):
        limit = 5
    if limit <= 0:
        return True
    return count_source_today(db, source.id, day_start_utc) >= limit


def _hold_video(
    db: Session,
    cand: DouyinVideo,
    *,
    level: str,
    reason: str,
) -> None:
    cand.status = "held"
    cand.match_level = level
    cand.hold_reason = reason[:2000]
    try:
        db.commit()
    except Exception:
        db.rollback()


def _reject_video(
    db: Session,
    cand: DouyinVideo,
    *,
    level: str,
    reason: str,
) -> None:
    cand.status = "rejected"
    cand.match_level = level
    cand.hold_reason = reason[:2000]
    try:
        db.commit()
    except Exception:
        db.rollback()


def _apply_keyword_action(
    db: Session,
    cand: DouyinVideo,
    source: DouyinSource,
    reason: str,
    *,
    policy: str,
    destination_id: str | None,
) -> None:
    """Route a keyword-filter hit through the matching verdict policy."""
    if policy == "mismatch":
        action = (source.mismatch_policy or "reject").lower()
    else:
        action = (source.borderline_policy or "hold").lower()
    logger.info(
        "Video %s keyword-filtered for destination %s: %s (action=%s)",
        cand.video_id,
        destination_id,
        reason,
        action,
    )
    cand.match_level = "mismatch" if policy == "mismatch" else "borderline"
    if action == "continue":
        return
    if action == "hold":
        _hold_video(db, cand, level=cand.match_level or policy, reason=reason)
    else:
        _reject_video(db, cand, level=cand.match_level or policy, reason=reason)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_local_now(timezone_name: str) -> datetime:
    tz_name = timezone_name or "UTC"
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    return datetime.now(tz)


def get_local_day_bounds(timezone_name: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    local_now = now or get_local_now(timezone_name)
    tz_name = timezone_name or "UTC"
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc

    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    local_end = local_start + timedelta(days=1)

    utc_start = local_start.astimezone(timezone.utc)
    utc_end = local_end.astimezone(timezone.utc)

    return utc_start, utc_end


def get_next_upload_slot(
    slots: list[str],
    timezone_name: str,
    now: datetime,
) -> datetime | None:
    slots = slots or list(SHORTS_DEFAULT_SLOTS)
    if not slots:
        return None

    tz_name = timezone_name or "UTC"
    try:
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo(tz_name)
    except Exception:
        local_tz = timezone.utc

    local_now = now.astimezone(local_tz)
    today_local = local_now.date()

    candidates: list[datetime] = []

    for time_str in slots:
        try:
            hour, minute = map(int, time_str.split(":"))
        except ValueError:
            continue

        slot_local = datetime.combine(today_local, datetime.min.time().replace(hour=hour, minute=minute))
        slot_local = slot_local.replace(tzinfo=local_tz)
        slot_utc = slot_local.astimezone(timezone.utc)
        candidates.append(slot_utc)

    candidates.sort()

    for slot in candidates:
        if slot <= now < slot + timedelta(minutes=10):
            return slot

    future = [slot for slot in candidates if slot > now]
    if future:
        return future[0]

    tomorrow_local = today_local + timedelta(days=1)
    try:
        hour, minute = map(int, slots[0].split(":"))
    except ValueError:
        return None

    slot_local = datetime.combine(tomorrow_local, datetime.min.time().replace(hour=hour, minute=minute))
    slot_local = slot_local.replace(tzinfo=local_tz)
    return slot_local.astimezone(timezone.utc)


def _try_pick_video(
    db: Session,
    pipeline: Pipeline,
    slot_type: str,
    destination: Destination | None = None,
) -> DouyinVideo | None:
    sources = db.execute(
        select(DouyinSource)
        .where(DouyinSource.pipeline_id == pipeline.id)
        .where(DouyinSource.enabled == True)  # noqa: E712
        .order_by(DouyinSource.created_at.asc())
    ).scalars().all()

    if not sources:
        return None

    cursor = pipeline.source_selection_cursor or 0
    day_start_utc: datetime | None = None
    if destination is not None:
        try:
            day_start_utc, _ = get_local_day_bounds(
                destination.timezone or "UTC", utcnow()
            )
        except Exception:
            day_start_utc = None
    if day_start_utc is None:
        now_utc = utcnow()
        day_start_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

    for i in range(len(sources)):
        idx = (cursor + i) % len(sources)
        source = sources[idx]

        # Per-source daily AUTO limit.
        if _source_daily_reached(db, source, day_start_utc):
            logger.info(
                "Source %s reached daily AUTO limit %s",
                source.id,
                source.max_videos_per_day,
            )
            continue

        query = (
            select(DouyinVideo)
            .where(DouyinVideo.source_id == source.id)
            .where(DouyinVideo.pipeline_id == pipeline.id)
            .where(DouyinVideo.status.in_(["new", "backlog"]))
            .where(DouyinVideo.status != "published")
        )

        if slot_type == "backlog":
            query = query.where(DouyinVideo.is_backlog == True)  # noqa: E712
        else:
            query = query.where(DouyinVideo.is_backlog == False)  # noqa: E712

        # Source order overrides pipeline backlog_order (default oldest first).
        desc_order = (pipeline.backlog_order or "asc").lower() == "desc"
        if (source.order or "oldest_first").lower() == "newest_first":
            desc_order = True
        elif (source.order or "").lower() == "oldest_first":
            desc_order = False
        if desc_order:
            query = query.order_by(DouyinVideo.douyin_created_at.desc())
        else:
            query = query.order_by(DouyinVideo.douyin_created_at.asc())

        candidates = db.execute(query.limit(50)).scalars().all()
        for cand in candidates:
            # Check content_match if destination or pipeline requires it
            niche = destination.metadata_profile if destination else pipeline.niche
            prompt_override = destination.prompt_override if destination else None

            text = f"{cand.title or ''}\n{cand.description or ''}"

            # Source keyword filters act like verdicts.
            if _keywords_hit(text, source.exclude_keywords):
                reason = (
                    "KEYWORD_EXCLUDED: video matches source exclude_keywords"
                )
                _apply_keyword_action(
                    db, cand, source, reason, policy="mismatch",
                    destination_id=destination.id if destination else None,
                )
                continue
            if (source.include_keywords or []) and not _keywords_hit(
                text, source.include_keywords
            ):
                reason = (
                    "KEYWORD_MISSING: video matches none of source "
                    "include_keywords"
                )
                _apply_keyword_action(
                    db, cand, source, reason, policy="borderline",
                    destination_id=destination.id if destination else None,
                )
                continue

            level, match_reason = evaluate_content_level(
                text,
                niche=niche,
                prompt_override=prompt_override,
            )
            cand.match_level = level

            if level == "match":
                pipeline.source_selection_cursor = (idx + 1) % len(sources)
                return cand

            if level == "borderline":
                policy = (source.borderline_policy or "hold").lower()
                if policy == "continue":
                    logger.info(
                        "Video %s borderline but source %s policy=continue",
                        cand.video_id,
                        source.id,
                    )
                    pipeline.source_selection_cursor = (idx + 1) % len(sources)
                    return cand
                logger.info(
                    "Video %s held (borderline) for destination %s: %s",
                    cand.video_id,
                    destination.id if destination else None,
                    match_reason,
                )
                _hold_video(db, cand, level=level, reason=match_reason)
                continue

            # mismatch
            policy = (source.mismatch_policy or "reject").lower()
            if policy == "hold":
                logger.info(
                    "Video %s held (mismatch) for destination %s: %s",
                    cand.video_id,
                    destination.id if destination else None,
                    match_reason,
                )
                _hold_video(db, cand, level=level, reason=match_reason)
            else:
                logger.warning(
                    "Video %s (%s) rejected by AI content match for destination %s: %s",
                    cand.video_id,
                    cand.title,
                    destination.id if destination else None,
                    match_reason,
                )
                _reject_video(db, cand, level=level, reason=match_reason)
            continue

    return None


def pick_video(
    db: Session,
    pipeline: Pipeline,
    slot_type: str,
    destination: Destination | None = None,
) -> DouyinVideo | None:
    video = _try_pick_video(db, pipeline, slot_type, destination=destination)
    if video is not None:
        return video

    other_type = "new" if slot_type == "backlog" else "backlog"
    return _try_pick_video(db, pipeline, other_type, destination=destination)


def count_todays_released_jobs(
    db: Session,
    pipeline: Pipeline,
    local_day_start_utc: datetime,
    destination: Destination | None = None,
) -> int:
    """Per-destination daily count (preferred) with pipeline fallback.

    When destination is given, count Publications for that destination
    created today excluding failed/skipped. Otherwise legacy pipeline
    VideoJob count.
    """
    today_start = local_day_start_utc
    today_end = today_start + timedelta(days=1)

    if destination is not None:
        pub_count = db.execute(
            select(func.count(Publication.id))
            .where(Publication.destination_id == destination.id)
            .where(Publication.created_at >= today_start)
            .where(Publication.created_at < today_end)
            .where(Publication.status.notin_(["failed", "skipped"]))
        ).scalar_one_or_none()
        job_count = db.execute(
            select(func.count(VideoJob.id))
            .where(VideoJob.destination_id == destination.id)
            .where(VideoJob.created_at >= today_start)
            .where(VideoJob.created_at < today_end)
            .where(
                VideoJob.status.in_(
                    ["published", "pending", "downloading", "uploading"]
                )
            )
        ).scalar_one_or_none()
        # Each schedule creates 1 Publication + 1 Job; take max to be safe
        # against legacy rows missing one side.
        return int(max(int(pub_count or 0), int(job_count or 0)))

    count = db.execute(
        select(func.count(VideoJob.id))
        .where(VideoJob.pipeline_id == pipeline.id)
        .where(VideoJob.created_at >= today_start)
        .where(VideoJob.created_at < today_end)
        .where(
            VideoJob.status.in_(
                ["published", "pending", "downloading", "uploading"]
            )
        )
    ).scalar_one_or_none()

    return count or 0


def get_slot_type(slot_index: int, backlog_slots: int, new_slots: int) -> str:
    total = max(backlog_slots + new_slots, 1)
    normalized = slot_index % total
    if normalized < backlog_slots:
        return "backlog"
    return "new"


# ---------------------------------------------------------------------------
# YouTube Shorts fixed rule: MAX 4 shorts/day/channel.
# ---------------------------------------------------------------------------

SHORTS_DEFAULT_SLOTS = ["10:00", "14:00", "18:00", "22:00"]
SHORTS_DEFAULT_TZ = "Asia/Ho_Chi_Minh"
SHORTS_MAX_SLOTS_PER_DAY = 4
SHORTS_MAX_LOOKAHEAD_DAYS = 365

# Publication statuses that hold (reserve) a daily slot.
SHORTS_RESERVED_STATUSES = {
    "queued",
    "scheduled",
    "downloading",
    "ai_metadata",
    "uploading",
    "processing",
    "pending",
}


def shorts_daily_limit(destination: Destination | None = None) -> int:
    """Hard cap: at most 4 shorts/day/channel (config-overridable)."""
    try:
        cap = int(getattr(settings, "youtube_shorts_daily_limit", 4) or 4)
    except (TypeError, ValueError):
        cap = 4
    cap = max(1, cap)
    if destination is not None:
        try:
            own = int(destination.daily_upload_limit or cap)
        except (TypeError, ValueError):
            own = cap
        # Destination limit may only lower the cap, never exceed it.
        return max(1, min(cap, own))
    return cap


def destination_tz(destination: Destination | None) -> str:
    tz = (getattr(destination, "timezone", None) or "").strip() if destination else ""
    return tz or SHORTS_DEFAULT_TZ


def destination_today(destination: Destination | None, now: datetime):
    """Local calendar date for a destination (fallback Asia/Ho_Chi_Minh)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(destination_tz(destination))
    except Exception:
        tz = timezone.utc
    return now.astimezone(tz).date()


def shorts_slots_for_day(destination: Destination | None) -> list[tuple[int, int]]:
    """Up to 4 (HH, MM) slots. Uses destination profile, else 10/14/18/22."""
    raw = (getattr(destination, "upload_slots", None) or []) if destination else []
    if not raw:
        raw = list(SHORTS_DEFAULT_SLOTS)
    out: list[tuple[int, int]] = []
    for item in raw:
        try:
            hh, mm = str(item).strip().split(":")[:2]
            h, m = int(hh), int(mm)
            if 0 <= h <= 23 and 0 <= m <= 59 and (h, m) not in out:
                out.append((h, m))
        except (ValueError, AttributeError, TypeError):
            continue
        if len(out) >= SHORTS_MAX_SLOTS_PER_DAY:
            break
    if not out:
        out = [(10, 0), (14, 0), (18, 0), (22, 0)]
    return out


def local_day_bounds_for_date(
    timezone_name: str, local_date
) -> tuple[datetime, datetime]:
    """UTC bounds for one local calendar date."""
    tz = _resolve_tz(timezone_name or SHORTS_DEFAULT_TZ)
    start_local = datetime.combine(
        local_date, datetime.min.time().replace(tzinfo=tz)
    )
    return (
        start_local.astimezone(timezone.utc),
        (start_local + timedelta(days=1)).astimezone(timezone.utc),
    )


def count_day_usage(
    db: Session,
    destination: Destination,
    local_date,
) -> tuple[int, int]:
    """Return (published, scheduled) shorts for a destination local date.

    Published counts rows with published_at inside the day. Scheduled counts
    rows in a slot-holding status with scheduled_at inside the day (legacy
    rows with NULL scheduled_at fall back to creation day). Failed/skipped
    never count.
    """
    tz_name = destination_tz(destination)
    day_start, day_end = local_day_bounds_for_date(tz_name, local_date)

    published = count_published_day(db, destination, local_date)

    reserved = db.execute(
        select(func.count(Publication.id))
        .where(Publication.destination_id == destination.id)
        .where(Publication.status.in_(list(SHORTS_RESERVED_STATUSES)))
        .where(
            Publication.scheduled_at >= day_start,
            Publication.scheduled_at < day_end,
        )
    ).scalar_one_or_none() or 0

    # Legacy reserved rows without scheduled_at: attribute by creation day.
    legacy = db.execute(
        select(func.count(Publication.id))
        .where(Publication.destination_id == destination.id)
        .where(Publication.status.in_(list(SHORTS_RESERVED_STATUSES)))
        .where(Publication.scheduled_at.is_(None))
        .where(Publication.created_at >= day_start)
        .where(Publication.created_at < day_end)
    ).scalar_one_or_none() or 0

    return int(published), int(reserved + legacy)


def count_published_day(
    db: Session,
    destination: Destination,
    local_date,
) -> int:
    """Published shorts for a destination local date (quota source of truth)."""
    tz_name = destination_tz(destination)
    day_start, day_end = local_day_bounds_for_date(tz_name, local_date)
    return int(
        db.execute(
            select(func.count(Publication.id))
            .where(Publication.destination_id == destination.id)
            .where(Publication.status == "published")
            .where(Publication.published_at >= day_start)
            .where(Publication.published_at < day_end)
        ).scalar_one_or_none()
        or 0
    )


def locked_destination(db: Session, destination_id: str) -> Destination | None:
    """Row-lock one destination for quota check+create atomicity.

    Serializes concurrent schedulers/manual publishes for the channel on
    Postgres (FOR UPDATE). Hold the lock until commit.
    """
    return db.execute(
        select(Destination)
        .where(Destination.id == destination_id)
        .with_for_update()
    ).scalar_one_or_none()


def extra_allowed_today(
    db: Session,
    destination: Destination,
    local_date,
) -> int:
    """Sum of user-approved extra slots for a destination local date."""
    from app.models import YouTubeDailyPublishOverride

    day_str = local_date.isoformat() if hasattr(local_date, "isoformat") else str(local_date)
    total = db.execute(
        select(func.coalesce(func.sum(YouTubeDailyPublishOverride.extra_allowed), 0))
        .where(YouTubeDailyPublishOverride.destination_id == destination.id)
        .where(YouTubeDailyPublishOverride.date == day_str)
    ).scalar_one_or_none()
    try:
        return max(0, int(total or 0))
    except (TypeError, ValueError):
        return 0


def day_allowance(
    db: Session,
    destination: Destination,
    local_date,
    include_override: bool,
) -> tuple[int, int, int]:
    """Return (published, extra, allowed) for manual quota decisions."""
    published = count_published_day(db, destination, local_date)
    extra = extra_allowed_today(db, destination, local_date) if include_override else 0
    return published, extra, shorts_daily_limit(destination) + extra


def is_slot_free(
    db: Session,
    destination: Destination,
    slot_utc: datetime,
) -> bool:
    """A slot is free when no active job claims its key and no active
    publication targets the same minute."""
    if slot_utc.tzinfo is None:
        slot_utc = slot_utc.replace(tzinfo=timezone.utc)
    key = f"{destination.id}:{slot_utc.isoformat()}"
    claimed = db.execute(
        select(VideoJob.id)
        .where(VideoJob.schedule_slot_key == key)
        .where(VideoJob.status.notin_(["failed"]))
        .limit(1)
    ).scalar_one_or_none()
    if claimed is not None:
        return False
    minute = slot_utc.replace(second=0, microsecond=0)
    # Reserved rows hold the minute; published rows keep history blocked too
    # (matches the partial unique index on reserved statuses: a published
    # row already passed through it, so the minute stays taken).
    rows = db.execute(
        select(Publication.scheduled_at)
        .where(Publication.destination_id == destination.id)
        .where(
            Publication.status.in_(list(SHORTS_RESERVED_STATUSES))
            | Publication.status.in_(["published", "failed"])
        )
        .where(Publication.scheduled_at.is_not(None))
    ).all()
    for (ts,) in rows:
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts.replace(second=0, microsecond=0) == minute:
            return False
    return True


def find_next_available_slot(
    db: Session,
    destination: Destination,
    now: datetime,
    start_date=None,
) -> tuple[Any, datetime] | None:
    """Nearest (local_date, slot_utc) with a free slot and day usage < 4.

    Skips past slots today. Never disturbs already-scheduled rows.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    tz_name = destination_tz(destination)
    tz = _resolve_tz(tz_name)
    limit = shorts_daily_limit(destination)
    slots = shorts_slots_for_day(destination)
    base_date = start_date or now.astimezone(tz).date()
    for offset in range(SHORTS_MAX_LOOKAHEAD_DAYS + 1):
        day = base_date + timedelta(days=offset)
        published, scheduled = count_day_usage(db, destination, day)
        if published + scheduled >= limit:
            continue
        for hh, mm in slots:
            slot_local = datetime.combine(
                day, datetime.min.time().replace(hour=hh, minute=mm, tzinfo=tz)
            )
            slot_utc = slot_local.astimezone(timezone.utc)
            if slot_utc <= now:
                continue
            if not is_slot_free(db, destination, slot_utc):
                continue
            return day, slot_utc
    return None


def get_capacity(
    db: Session,
    destination: Destination,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Capacity snapshot for UI/API. Read-only."""
    now = now or utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    tz_name = destination_tz(destination)
    tz = _resolve_tz(tz_name)
    today = now.astimezone(tz).date()
    limit = shorts_daily_limit(destination)
    published, scheduled = count_day_usage(db, destination, today)
    used = published + scheduled
    extra = extra_allowed_today(db, destination, today)
    queued = db.execute(
        select(func.count(Publication.id))
        .where(Publication.destination_id == destination.id)
        .where(Publication.status == "queued")
    ).scalar_one_or_none() or 0
    nxt = find_next_available_slot(db, destination, now)
    return {
        "destination_id": destination.id,
        "daily_limit": limit,
        "timezone": tz_name,
        "today": today.isoformat(),
        "published_today": int(published),
        "scheduled_today": int(scheduled),
        "used_today": int(used),
        "remaining_today": max(0, limit - used),
        "extra_allowed_today": int(extra),
        "allowed_today": int(limit + extra),
        "queued": int(queued),
        "next_available_slot": nxt[1].isoformat() if nxt else None,
    }


def allocate_publication(
    db: Session,
    destination: Destination,
    pipeline: Pipeline,
    douyin_video: DouyinVideo,
    now: datetime,
    publication_mode: str = "auto",
    title: str | None = None,
    description: str | None = None,
) -> tuple[Publication, datetime, Any] | None:
    """Persist one queued publication on the nearest free slot (FIFO-safe).

    Creates NO VideoJob: jobs are created by promote_due_publications when
    the slot becomes due, so future days never leak into the worker early.
    Retries forward on slot collision (concurrent workers).
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    for _ in range(SHORTS_MAX_SLOTS_PER_DAY * 4):
        # Serialize concurrent allocators on Postgres; single commit below
        # keeps check+insert atomic per attempt.
        try:
            locked_destination(db, destination.id)
        except Exception:
            pass
        found = find_next_available_slot(db, destination, now)
        if found is None:
            try:
                db.rollback()
            except Exception:
                pass
            return None
        day, slot_utc = found
        # Skip if this video already has an active publication here.
        existing = db.execute(
            select(Publication)
            .where(Publication.douyin_video_id == douyin_video.id)
            .where(Publication.destination_id == destination.id)
            .where(Publication.status.notin_(["failed", "skipped", "published"]))
            .limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            return existing, existing.scheduled_at or slot_utc, day
        pub = Publication(
            pipeline_id=pipeline.id,
            douyin_video_id=douyin_video.id,
            destination_id=destination.id,
            platform=destination.platform,
            publication_mode=publication_mode,
            status="queued",
            scheduled_at=slot_utc,
            title=title,
            description=description,
        )
        try:
            sched_tz = destination_tz(destination)
            try:
                pub.youtube_publish_mode = "immediate"
                pub.youtube_schedule_timezone = sched_tz
                pub.youtube_scheduled = False
                pub.youtube_privacy_status = "public"
            except Exception:
                pass
        except Exception:
            pass
        db.add(pub)
        try:
            db.commit()
            db.refresh(pub)
            return pub, slot_utc, day
        except IntegrityError:
            db.rollback()
            # Either the slot was taken concurrently (retry forward) or
            # this video already has an active publication here (reuse it).
            existing = db.execute(
                select(Publication)
                .where(Publication.douyin_video_id == douyin_video.id)
                .where(Publication.destination_id == destination.id)
                .where(Publication.status.notin_(["failed", "skipped", "published"]))
                .limit(1)
            ).scalar_one_or_none()
            if existing is not None:
                return existing, existing.scheduled_at or slot_utc, day
            continue
    return None


def promote_due_publications(
    db: Session,
    destination: Destination,
    now: datetime,
    grace_minutes: int = 10,
) -> int:
    """Create pending jobs for queued publications whose slot is due.

    FIFO by (scheduled_at, created_at). Respects the 4/day cap and claims
    each slot via schedule_slot_key so concurrent workers cannot double
    schedule. Returns number of jobs created.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    due_before = now + timedelta(minutes=max(0, grace_minutes))
    queued = list(
        db.execute(
            select(Publication)
            .where(Publication.destination_id == destination.id)
            .where(Publication.status == "queued")
            .where(Publication.scheduled_at.is_not(None))
            .where(Publication.scheduled_at <= due_before)
            .order_by(Publication.scheduled_at.asc(), Publication.created_at.asc())
            .limit(50)
        )
        .scalars()
        .all()
    )
    created = 0
    promoted_this_run = 0
    pipeline = db.get(Pipeline, destination.pipeline_id)
    for pub in queued:
        slot_utc = pub.scheduled_at
        if slot_utc is None:
            continue
        if slot_utc.tzinfo is None:
            slot_utc = slot_utc.replace(tzinfo=timezone.utc)
        tz_name = destination_tz(destination)
        local_day = slot_utc.astimezone(_resolve_tz(tz_name)).date()
        # Scheduler/auto NEVER consumes override headroom: hard cap 4
        # published. In-run counter stops catch-up bursts from overshooting.
        published = count_published_day(db, destination, local_day)
        if published + promoted_this_run >= shorts_daily_limit(destination):
            continue
        slot_key = f"{destination.id}:{slot_utc.isoformat()}"
        taken = db.execute(
            select(VideoJob.id)
            .where(VideoJob.schedule_slot_key == slot_key)
            .where(VideoJob.status.notin_(["failed"]))
            .limit(1)
        ).scalar_one_or_none()
        if taken is not None:
            # Already promoted (e.g. by a concurrent worker): just flip state.
            if pub.status == "queued":
                pub.status = "scheduled"
                try:
                    db.commit()
                except Exception:
                    db.rollback()
            continue
        video = db.get(DouyinVideo, pub.douyin_video_id)
        if video is None:
            continue
        job = VideoJob(
            source_url=video.url,
            source_title=video.title,
            title=pub.title,
            description=pub.description or video.description,
            privacy_status=(pipeline.default_privacy if pipeline else "public"),
            status="pending",
            pipeline_id=pub.pipeline_id,
            source_video_id=video.video_id,
            destination_id=destination.id,
            publication_id=pub.id,
            schedule_slot_key=slot_key,
        )
        try:
            sched_tz = destination_tz(destination)
            try:
                job.youtube_publish_mode = "immediate"
                job.youtube_schedule_timezone = sched_tz
                job.youtube_scheduled = False
            except Exception:
                pass
        except Exception:
            pass
        db.add(job)
        pub.status = "scheduled"
        try:
            db.commit()
            created += 1
            promoted_this_run += 1
        except IntegrityError:
            db.rollback()
            continue
    return created


def count_inventory_available(db: Session, pipeline: Pipeline) -> int:
    count = db.execute(
        select(func.count(DouyinVideo.id))
        .where(DouyinVideo.pipeline_id == pipeline.id)
        .where(DouyinVideo.status.in_(["new", "backlog"]))
    ).scalar_one_or_none()
    return int(count or 0)


def is_destination_ready(
    destination: Destination,
) -> tuple[bool, str | None]:
    """Destination must be connected before any Publication/VideoJob is made."""
    if not destination.enabled:
        return False, REASON_DISABLED
    if (destination.platform or "").lower() != "youtube":
        return False, "UNSUPPORTED_PLATFORM"
    if not destination.connected:
        return False, REASON_NOT_CONNECTED
    if not destination.credentials:
        return False, REASON_NOT_CONNECTED
    return True, None


def _mark_destination_cycle(
    db: Session,
    destination: Destination,
    now: datetime,
    skip_reason: str | None,
    job_created: bool = False,
) -> None:
    try:
        destination.last_scheduler_check_at = now
        destination.last_cycle_at = now
        destination.last_skip_reason = skip_reason
        if job_created:
            destination.last_job_created_at = now
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


SLOT_GRACE_MINUTES = 10
CATCHUP_MAX_HOURS = 24


def _resolve_tz(timezone_name: str):
    tz_name = timezone_name or "UTC"
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz_name)
    except Exception:
        return timezone.utc


def get_slots_between(
    slots: list[str],
    timezone_name: str,
    start: datetime,
    end: datetime,
) -> list[datetime]:
    """Enumerate all upload slot datetimes (UTC) with start < slot <= end."""
    if not slots:
        return []
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if end <= start:
        return []
    local_tz = _resolve_tz(timezone_name)
    start_local = start.astimezone(local_tz)
    end_local = end.astimezone(local_tz)
    results: list[datetime] = []
    day = start_local.date()
    last_day = end_local.date()
    while day <= last_day:
        for time_str in slots:
            try:
                hour, minute = map(int, str(time_str).split(":"))
            except ValueError:
                continue
            try:
                slot_local = datetime.combine(
                    day, datetime.min.time().replace(hour=hour, minute=minute)
                ).replace(tzinfo=local_tz)
            except ValueError:
                continue
            slot_utc = slot_local.astimezone(timezone.utc)
            if start < slot_utc <= end:
                results.append(slot_utc)
        day = day + timedelta(days=1)
    results.sort()
    return results


def get_due_slots(
    slots: list[str],
    timezone_name: str,
    now: datetime,
    last_check: datetime | None,
    catchup_max_hours: int = CATCHUP_MAX_HOURS,
) -> list[datetime]:
    """Return due slots including catch-up for missed windows.

    - Normal steady state: only the current grace-window slot is due.
    - After sleep/restart: every slot in (last_check, now] is due (capped
      at catchup_max_hours, default 24h) plus the current grace slot.
    Deduplication is enforced by schedule_slot_key downstream.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    due: list[datetime] = []
    seen: set[str] = set()

    def _add(slot: datetime):
        key = slot.isoformat()
        if key not in seen:
            seen.add(key)
            due.append(slot)

    # Current grace-window slot always qualifies (if any).
    current = get_next_upload_slot(slots or [], timezone_name, now)
    if current is not None and (
        current <= now < current + timedelta(minutes=SLOT_GRACE_MINUTES)
    ):
        _add(current)

    if last_check is not None:
        if last_check.tzinfo is None:
            last_check = last_check.replace(tzinfo=timezone.utc)
        capped = max(last_check, now - timedelta(hours=catchup_max_hours))
        for slot in get_slots_between(slots or [], timezone_name, capped, now):
            _add(slot)
    elif current is None:
        pass

    due.sort()
    return due


def schedule_for_destination(
    db: Session,
    destination: Destination,
    now: datetime | None = None,
    catchup_max_hours: int = CATCHUP_MAX_HOURS,
) -> None:
    if now is None:
        now = utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if not destination.enabled:
        _mark_destination_cycle(db, destination, now, REASON_DISABLED)
        return

    pipeline = db.get(Pipeline, destination.pipeline_id)
    if pipeline is None or not pipeline.enabled:
        _mark_destination_cycle(db, destination, now, REASON_DISABLED)
        return

    # Destination must be connected before scheduling (no late worker fail).
    ready, reason = is_destination_ready(destination)
    if not ready:
        logger.warning(
            "destination_not_connected destination=%s platform=%s connected=%s",
            destination.id,
            destination.platform,
            destination.connected,
        )
        _mark_destination_cycle(
            db, destination, now, reason or REASON_NOT_CONNECTED
        )
        return

    # 0. Promote queued batch-import publications whose slot is due.
    # FIFO by (scheduled_at, created_at); slot-key claim stops duplicates.
    try:
        promote_due_publications(db, destination, now)
    except Exception:
        logger.exception(
            "Failed to promote queued publications for destination %s",
            destination.id,
        )

    # Fixed rule: at most 4 slots/day/channel (profile slots, else default).
    slots = [f"{h:02d}:{m:02d}" for h, m in shorts_slots_for_day(destination)]
    if not slots:
        _mark_destination_cycle(db, destination, now, REASON_WAITING_SLOT)
        return

    last_check = destination.last_scheduler_check_at
    if last_check is not None and last_check.tzinfo is None:
        last_check = last_check.replace(tzinfo=timezone.utc)

    due_slots = get_due_slots(
        slots, destination.timezone, now, last_check, catchup_max_hours
    )

    if not due_slots:
        try:
            nxt = get_next_upload_slot(slots, destination.timezone, now)
            logger.info(
                "Destination %s next slot %s, outside grace window",
                destination.id,
                nxt,
            )
        except Exception:
            pass
        _mark_destination_cycle(db, destination, now, REASON_WAITING_SLOT)
        return

    created_any = False

    for slot in due_slots:
        # Fixed rule: max 4 shorts/day/channel, counting published +
        # scheduled-for-today in the destination timezone.
        tz_name = destination_tz(destination)
        slot_day = slot.astimezone(_resolve_tz(tz_name)).date()
        _pub_n, _sch_n = count_day_usage(db, destination, slot_day)
        _cap = shorts_daily_limit(destination)
        if _pub_n + _sch_n >= _cap:
            logger.info(
                "Destination %s reached daily limit %s/%s on %s",
                destination.id,
                _pub_n + _sch_n,
                _cap,
                slot_day.isoformat(),
            )
            _mark_destination_cycle(db, destination, now, REASON_DAILY_LIMIT)
            return

        # Minimum interval between YouTube uploads for this destination.
        try:
            min_interval = int(destination.min_upload_interval_minutes or 0)
        except (TypeError, ValueError):
            min_interval = 0
        if min_interval > 0:
            last_pub_at = db.execute(
                select(func.max(Publication.created_at))
                .where(Publication.destination_id == destination.id)
                .where(Publication.status.notin_(["failed", "skipped"]))
            ).scalar_one_or_none()
            ref = destination.last_job_created_at or last_pub_at
            if ref is not None:
                if ref.tzinfo is None:
                    ref = ref.replace(tzinfo=timezone.utc)
                elapsed = (now - ref).total_seconds()
                if elapsed < min_interval * 60:
                    logger.info(
                        "Destination %s upload interval wait %.0fs < %sm",
                        destination.id,
                        elapsed,
                        min_interval,
                    )
                    _mark_destination_cycle(
                        db, destination, now, REASON_UPLOAD_INTERVAL
                    )
                    return

        slot_index = slot.hour * 60 + slot.minute
        slot_type = get_slot_type(
            slot_index,
            destination.backlog_slots_per_day or 4,
            destination.new_slots_per_day or 2,
        )

        video = pick_video(db, pipeline, slot_type, destination=destination)
        if video is None:
            logger.warning(
                "NO_AVAILABLE_INVENTORY destination=%s slot=%s type=%s",
                destination.id,
                slot.isoformat(),
                slot_type,
            )
            _mark_destination_cycle(db, destination, now, REASON_NO_INVENTORY)
            return

        slot_key = f"{destination.id}:{slot.isoformat()}"

        # Idempotency: schedule_slot_key unique prevents duplicates after
        # restart / catch-up replays.
        existing = db.execute(
            select(VideoJob)
            .where(VideoJob.schedule_slot_key == slot_key)
            .limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            logger.info(
                "Destination %s slot %s already claimed, skipping",
                destination.id,
                slot_key,
            )
            continue

        # Resolve native YouTube publish intent (per-channel default wins,
        # pipeline strategy is fallback). Auto scheduler never hardcodes UTC:
        # it uses the destination timezone for slot math.
        dest_mode = (getattr(destination, "youtube_default_publish_mode", None) or "immediate").lower()
        pipe_mode = (getattr(pipeline, "youtube_default_publish_mode", None) or "immediate").lower()
        if dest_mode not in ("immediate", "scheduled", "private", "unlisted"):
            dest_mode = "immediate"
        if pipe_mode not in ("immediate", "scheduled", "private", "unlisted"):
            pipe_mode = "immediate"
        effective_mode = dest_mode if dest_mode != "immediate" else pipe_mode
        sched_tz = destination.timezone or "UTC"
        yt_publish_at = None
        yt_privacy = pipeline.default_privacy or "public"
        if effective_mode == "scheduled":
            from app.youtube_scheduling import find_next_free_slot as _find_slot

            try:
                existing_pub_ats = db.execute(
                    select(Publication.youtube_publish_at)
                    .where(Publication.destination_id == destination.id)
                    .where(Publication.youtube_publish_at.is_not(None))
                    .where(Publication.status.in_(["scheduled", "queued", "uploading", "processing"]))
                ).all()
                used = {r[0].isoformat() for r in existing_pub_ats if r[0] is not None}
            except Exception:
                used = set()
            yt_publish_at = _find_slot(
                slots, sched_tz, used, now=now, allow_collision=False
            )
            if yt_publish_at is None:
                logger.warning(
                    "No free YouTube slot for destination=%s, skipping",
                    destination.id,
                )
                _mark_destination_cycle(db, destination, now, REASON_WAITING_SLOT)
                return
            yt_privacy = "private"
        elif effective_mode == "private":
            yt_privacy = "private"
        elif effective_mode == "unlisted":
            yt_privacy = "unlisted"
        else:
            yt_privacy = "public"

        publication = Publication(
            pipeline_id=pipeline.id,
            douyin_video_id=video.id,
            destination_id=destination.id,
            platform=destination.platform,
            status="scheduled",
            scheduled_at=slot,
        )
        # Native scheduling intent (additive columns may not exist on old SQLite
        # test DBs — set defensively).
        for _k, _v in {
            "youtube_publish_mode": effective_mode,
            "youtube_publish_at": yt_publish_at,
            "youtube_schedule_timezone": sched_tz,
            "youtube_scheduled": False,
            "youtube_privacy_status": yt_privacy,
        }.items():
            try:
                setattr(publication, _k, _v)
            except Exception:
                pass
        db.add(publication)
        try:
            db.flush()  # assign publication.id for job link
        except IntegrityError:
            db.rollback()
            logger.info(
                "Destination %s publication already exists, skipping slot %s",
                destination.id,
                slot_key,
            )
            continue

        job = VideoJob(
            source_url=video.url,
            source_title=video.title,
            title=None,
            description=video.description,
            privacy_status=yt_privacy,
            status="pending",
            pipeline_id=pipeline.id,
            source_video_id=video.video_id,
            destination_id=destination.id,
            publication_id=publication.id,
            schedule_slot_key=slot_key,
        )
        for _k, _v in {
            "youtube_publish_mode": effective_mode,
            "youtube_publish_at": yt_publish_at,
            "youtube_schedule_timezone": sched_tz,
            "youtube_scheduled": False,
        }.items():
            try:
                setattr(job, _k, _v)
            except Exception:
                pass
        db.add(job)

        video.status = "scheduled"
        video.scheduled_at = now

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            logger.info(
                "Destination %s slot %s already claimed, skipping",
                destination.id,
                slot_key,
            )
            continue

        created_any = True
        logger.info(
            "Scheduled video %s for destination %s at slot %s",
            video.video_id,
            destination.id,
            slot,
        )

    _mark_destination_cycle(
        db, destination, now, None if created_any else REASON_WAITING_SLOT,
        job_created=created_any,
    )


def schedule_for_pipeline(
    db: Session,
    pipeline: Pipeline,
    now: datetime | None = None,
) -> None:
    destination = db.execute(
        select(Destination)
        .where(Destination.pipeline_id == pipeline.id)
        .where(Destination.enabled == True)  # noqa: E712
        .limit(1)
    ).scalar_one_or_none()

    if destination is None:
        return

    schedule_for_destination(db, destination, now=now)


def run_scheduler_once() -> None:
    with SessionLocal() as db:
        destinations = db.execute(
            select(Destination)
            .where(Destination.enabled == True)  # noqa: E712
        ).scalars().all()

        # Detach ids first: schedule_for_destination commits per destination.
        dest_ids = [d.id for d in destinations]

        for dest_id in dest_ids:
            try:
                with SessionLocal() as ddb:
                    destination = ddb.get(Destination, dest_id)
                    if destination is None:
                        continue
                    # Reattach pipeline check inside schedule_for_destination.
                    schedule_for_destination(ddb, destination)
            except Exception:
                logger.exception(
                    "Failed to schedule destination %s",
                    dest_id,
                )


async def scheduler_loop() -> None:
    if not getattr(settings, "scheduler_enabled", True):
        logger.info("Douyin scheduler is disabled")
        return

    startup_delay = getattr(settings, "scheduler_startup_delay_seconds", 10)
    poll_interval = getattr(settings, "scheduler_poll_seconds", 60)

    logger.info("Douyin scheduler started, waiting %s seconds before first run", startup_delay)
    await asyncio.sleep(startup_delay)

    while True:
        try:
            logger.info("Starting scheduler cycle")
            await asyncio.to_thread(run_scheduler_once)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduler loop error")

        logger.info("Scheduler sleeping for %s seconds", poll_interval)
        await asyncio.sleep(poll_interval)
