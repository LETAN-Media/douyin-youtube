"""Publication reschedule: one contract for validation and consistent writes.

The dashboard only ever sends an absolute UTC timestamp (ISO 8601 with an
offset). Every business rule lives here so the API cannot be bypassed:

- the new time must be in the future (safety margin),
- the target minute must be free on the same YouTube destination,
- the destination daily upload limit must still have room,
- the minimum upload interval between two publishes must be respected,
- published / in-flight publications are never touched,
- a video already scheduled natively on YouTube is moved through the YouTube
  API (videos.update), never by editing the database alone.

Writes update Publication and its linked VideoJob rows in one transaction, move
the reservation (new schedule_slot_key) and never create jobs or trigger an
upload. No other publication, pipeline or destination is modified.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Destination, DouyinVideo, Publication, VideoJob
from app.schedule_policy import ScheduleError, effective_schedule
from app.scheduler import SHORTS_RESERVED_STATUSES, count_day_usage

# Same margin the YouTube scheduling contract uses: past/immediate times are
# rejected instead of silently publishing.
RESCHEDULE_MIN_MARGIN = timedelta(minutes=5)

# A publication in one of these states is already being handed to the platform.
BLOCKED_PUBLICATION_STATUSES = {"uploading", "processing"}
IN_FLIGHT_JOB_STATUSES = {"downloading", "uploading", "upload_processing", "processing"}

SLOT_HOLDING_STATUSES = tuple(SHORTS_RESERVED_STATUSES) + ("published",)
MAX_LOOKAHEAD_DAYS = 120
MAX_SLOT_HINTS = 3


class RescheduleError(Exception):
    """API-facing reschedule failure with an explicit status and reason code."""

    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(f"{code}: {message}")


# ---------------------------------------------------------------------------
# Time helpers (never rely on the browser or server local timezone)
# ---------------------------------------------------------------------------

def resolve_tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo((name or "UTC").strip() or "UTC")
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return ZoneInfo("UTC")


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def minute_of(dt: datetime) -> datetime:
    return ensure_utc(dt).replace(second=0, microsecond=0)


def gmt_offset_label(local: datetime) -> str:
    offset = local.utcoffset() or timedelta(0)
    total = int(offset.total_seconds()) // 60
    sign = "+" if total >= 0 else "-"
    hours, minutes = divmod(abs(total), 60)
    suffix = f":{minutes:02d}" if minutes else ""
    return f"GMT{sign}{hours}{suffix}"


def format_local_label(dt: datetime | None, tz_name: str | None) -> str | None:
    """UI label, e.g. '20:30 — 02/11/2026 (GMT+7)'."""
    if dt is None:
        return None
    local = ensure_utc(dt).astimezone(resolve_tz(tz_name))
    return f"{local:%H:%M} — {local:%d/%m/%Y} ({gmt_offset_label(local)})"


def format_timezone_label(tz_name: str | None, at: datetime | None = None) -> str:
    name = (tz_name or "UTC").strip() or "UTC"
    anchor = ensure_utc(at or datetime.now(timezone.utc)).astimezone(resolve_tz(name))
    return f"{name} ({gmt_offset_label(anchor)})"


# ---------------------------------------------------------------------------
# State inspection
# ---------------------------------------------------------------------------

def _schedule_for(destination: Destination):
    try:
        return effective_schedule(destination)
    except ScheduleError as exc:
        raise RescheduleError(
            "INVALID_SCHEDULE_CONFIG",
            f"Cấu hình lịch của kênh không hợp lệ: {exc}",
            status_code=409,
        ) from exc


def linked_jobs(db: Session, publication: Publication) -> list[VideoJob]:
    return list(
        db.execute(
            select(VideoJob).where(VideoJob.publication_id == publication.id)
        ).scalars().all()
    )


def youtube_flags(publication: Publication) -> tuple[bool, bool]:
    """Return (uploaded_to_youtube, native_scheduled_on_youtube)."""
    uploaded = bool(publication.external_post_id)
    native = uploaded and bool(getattr(publication, "youtube_scheduled", False))
    return uploaded, native


def blocking_reason(db: Session, publication: Publication) -> str | None:
    """Why this publication can no longer be rescheduled (None when allowed)."""
    status = (publication.status or "").lower()
    if status == "published":
        return "Publication đã Published, không thể đổi lịch."
    if status in BLOCKED_PUBLICATION_STATUSES:
        return (
            f"Publication đang {publication.status}; không thể đổi lịch khi job "
            "đang Uploading/Processing."
        )
    for job in linked_jobs(db, publication):
        if (job.status or "").lower() in IN_FLIGHT_JOB_STATUSES:
            return (
                f"Job đang {job.status}; chờ upload xong rồi mới đổi lịch."
            )
    uploaded, native = youtube_flags(publication)
    if uploaded and not native and (publication.platform or "").lower() == "youtube":
        return (
            "Video đã có trên YouTube nhưng không ở chế độ lên lịch native; "
            "không hỗ trợ đổi lịch cho publication này."
        )
    return None


def _other_slot_publications(
    db: Session, publication: Publication
) -> list[Publication]:
    return list(
        db.execute(
            select(Publication)
            .where(Publication.destination_id == publication.destination_id)
            .where(Publication.id != publication.id)
            .where(Publication.status.in_(list(SLOT_HOLDING_STATUSES)))
        ).scalars().all()
    )


def _slot_taken(db: Session, publication: Publication, at: datetime) -> bool:
    target = minute_of(at)
    for other in _other_slot_publications(db, publication):
        if other.scheduled_at is None or other.status not in SLOT_HOLDING_STATUSES:
            continue
        if minute_of(other.scheduled_at) == target:
            return True
    key = f"{publication.destination_id}:{target.isoformat()}"
    claimed = db.execute(
        select(VideoJob.id)
        .where(VideoJob.schedule_slot_key == key)
        .where(VideoJob.status.notin_(["failed"]))
        .where(
            or_(
                VideoJob.publication_id.is_(None),
                VideoJob.publication_id != publication.id,
            )
        )
        .limit(1)
    ).scalar_one_or_none()
    return claimed is not None


def _interval_conflict(
    db: Session,
    publication: Publication,
    at: datetime,
    minimum_minutes: int,
) -> Publication | None:
    gap = timedelta(minutes=max(1, int(minimum_minutes or 1)))
    target = ensure_utc(at)
    for other in _other_slot_publications(db, publication):
        if other.status in {"failed", "skipped"}:
            continue
        for stamp in (other.scheduled_at, other.published_at):
            if stamp is None:
                continue
            delta = abs(ensure_utc(stamp) - target)
            if delta < gap:
                return other
    return None


def _daily_usage_excluding_self(
    db: Session, publication: Publication, destination: Destination, local_date
) -> tuple[int, int]:
    published, scheduled = count_day_usage(db, destination, local_date)
    own = minute_of(publication.scheduled_at) if publication.scheduled_at else None
    tz = resolve_tz(destination_tz_name(destination))
    if publication.status == "published" and publication.published_at is not None:
        if ensure_utc(publication.published_at).astimezone(tz).date() == local_date:
            published = max(0, published - 1)
    elif own is not None and publication.status in SHORTS_RESERVED_STATUSES:
        if own.astimezone(tz).date() == local_date:
            scheduled = max(0, scheduled - 1)
    return int(published), int(scheduled)


def destination_tz_name(destination: Destination) -> str:
    try:
        return _schedule_for(destination).timezone or "Asia/Ho_Chi_Minh"
    except RescheduleError:
        return "Asia/Ho_Chi_Minh"


def _configured_slots(destination: Destination) -> list[tuple[int, int]]:
    slots: list[tuple[int, int]] = []
    for raw in _schedule_for(destination).upload_slots or []:
        try:
            hour, minute = map(int, str(raw).strip().split(":"))
        except (ValueError, TypeError):
            continue
        slots.append((hour, minute))
    return sorted(set(slots))


def _slot_datetime(local_date, hour: int, minute: int, tz: ZoneInfo) -> datetime:
    return datetime.combine(
        local_date, datetime.min.time().replace(hour=hour, minute=minute)
    ).replace(tzinfo=tz)


def _next_free_slot(
    db: Session,
    publication: Publication,
    destination: Destination,
    now: datetime,
) -> datetime | None:
    """Nearest future configured slot that passes every reschedule rule."""
    tz = resolve_tz(destination_tz_name(destination))
    schedule = _schedule_for(destination)
    slots = _configured_slots(destination)
    if not slots:
        return None
    cursor = ensure_utc(now)
    base_date = cursor.astimezone(tz).date()
    for offset in range(MAX_LOOKAHEAD_DAYS + 1):
        day = base_date + timedelta(days=offset)
        published, scheduled = _daily_usage_excluding_self(
            db, publication, destination, day
        )
        if published + scheduled >= schedule.daily_upload_limit:
            continue
        for hour, minute in slots:
            candidate = _slot_datetime(day, hour, minute, tz)
            if candidate <= cursor + RESCHEDULE_MIN_MARGIN:
                continue
            if _slot_taken(db, publication, candidate):
                continue
            if _interval_conflict(
                db, publication, candidate, schedule.min_upload_interval_minutes
            ):
                continue
            return candidate.astimezone(timezone.utc)
    return None


def _next_configured_slot(destination: Destination, now: datetime) -> datetime:
    """Last-resort suggestion (no fully free slot): next configured time."""
    tz = resolve_tz(destination_tz_name(destination))
    slots = _configured_slots(destination) or [(8, 0)]
    local_now = ensure_utc(now).astimezone(tz)
    for offset in range(MAX_LOOKAHEAD_DAYS + 1):
        day = local_now.date() + timedelta(days=offset)
        for hour, minute in slots:
            candidate = _slot_datetime(day, hour, minute, tz)
            if candidate > ensure_utc(now) + RESCHEDULE_MIN_MARGIN:
                return candidate.astimezone(timezone.utc)
    return (ensure_utc(now) + timedelta(minutes=10)).replace(
        second=0, microsecond=0
    )


def next_free_slots(
    db: Session,
    publication: Publication,
    destination: Destination,
    now: datetime,
    count: int = MAX_SLOT_HINTS,
) -> list[datetime]:
    hints: list[datetime] = []
    cursor = ensure_utc(now)
    for _ in range(max(1, count)):
        found = _next_free_slot(db, publication, destination, cursor)
        if found is None:
            break
        hints.append(found)
        cursor = found + timedelta(minutes=1)
    return hints


# ---------------------------------------------------------------------------
# Options payload for the dashboard modal
# ---------------------------------------------------------------------------

def build_reschedule_options(
    db: Session, publication: Publication, now: datetime | None = None
) -> dict[str, Any]:
    now = ensure_utc(now or datetime.now(timezone.utc))
    destination = db.get(Destination, publication.destination_id)
    if destination is None:
        raise RescheduleError(
            "DESTINATION_NOT_FOUND",
            "Không tìm thấy destination của publication.",
            status_code=404,
        )
    schedule = _schedule_for(destination)
    tz_name = schedule.timezone or "Asia/Ho_Chi_Minh"
    video = db.get(DouyinVideo, publication.douyin_video_id)
    current = publication.scheduled_at
    current_future = current is not None and ensure_utc(current) > now + RESCHEDULE_MIN_MARGIN
    hint = _next_free_slot(db, publication, destination, now)
    if hint is None:
        hint = _next_configured_slot(destination, now)
    uploaded, native = youtube_flags(publication)
    tz = resolve_tz(tz_name)
    published_today, scheduled_today = _daily_usage_excluding_self(
        db, publication, destination, hint.astimezone(tz).date()
    )
    return {
        "publication_id": publication.id,
        "video_title": (publication.title or (video.title if video else None)),
        "destination_id": destination.id,
        "destination_name": destination.name,
        "platform": publication.platform,
        "status": publication.status,
        "publication_mode": publication.publication_mode or "auto",
        "scheduled_at": ensure_utc(current) if current is not None else None,
        "scheduled_at_label": format_local_label(current, tz_name),
        "timezone": tz_name,
        "timezone_label": format_timezone_label(tz_name, now),
        "suggested_at": hint,
        "suggested_at_label": format_local_label(hint, tz_name),
        "current_is_future": current_future,
        "can_reschedule": blocking_reason(db, publication) is None,
        "block_reason": blocking_reason(db, publication),
        "daily_limit": int(schedule.daily_upload_limit),
        "used_on_target_day": int(published_today + scheduled_today),
        "minimum_interval_minutes": int(schedule.min_upload_interval_minutes),
        "youtube_uploaded": uploaded,
        "youtube_native": native,
        "next_free_slots": [
            {"at": slot, "label": format_local_label(slot, tz_name)}
            for slot in next_free_slots(db, publication, destination, now)
        ],
    }


# ---------------------------------------------------------------------------
# Reschedule write path
# ---------------------------------------------------------------------------

@dataclass
class ReschedulePlan:
    destination: Destination
    schedule: Any
    timezone_name: str
    new_at: datetime
    previous_at: datetime | None
    youtube_native: bool


def _normalize_target(
    value: datetime, tz_name: str | None
) -> datetime:
    if not isinstance(value, datetime):
        raise RescheduleError(
            "INVALID_SCHEDULE_TIME",
            "scheduled_at phải là ISO 8601 datetime.",
            status_code=400,
        )
    if value.tzinfo is None:
        if not tz_name:
            raise RescheduleError(
                "INVALID_SCHEDULE_TIME",
                "scheduled_at phải kèm timezone offset (ISO 8601), ví dụ "
                "2026-11-02T13:30:00Z. Không nhận giờ local không rõ múi giờ.",
                status_code=400,
            )
        value = value.replace(tzinfo=resolve_tz(tz_name))
    return minute_of(value)


def validate_reschedule(
    db: Session,
    publication: Publication,
    destination: Destination,
    schedule: Any,
    new_at: datetime,
    now: datetime,
) -> None:
    reason = blocking_reason(db, publication)
    if reason is not None:
        if (publication.status or "").lower() == "published":
            raise RescheduleError("PUBLICATION_ALREADY_PUBLISHED", reason, 409)
        if (publication.status or "").lower() in BLOCKED_PUBLICATION_STATUSES:
            raise RescheduleError("PUBLICATION_IN_PROGRESS", reason, 409)
        if "Job đang" in reason:
            raise RescheduleError("PUBLICATION_IN_PROGRESS", reason, 409)
        raise RescheduleError("YOUTUBE_RESCHEDULE_UNSUPPORTED", reason, 409)

    if new_at <= now + RESCHEDULE_MIN_MARGIN:
        raise RescheduleError(
            "INVALID_SCHEDULE_TIME",
            "Thời điểm mới phải ở tương lai (ít nhất 5 phút).",
            status_code=400,
        )

    tz = resolve_tz(schedule.timezone)
    local_day = new_at.astimezone(tz).date()
    suggestion = _next_free_slot(db, publication, destination, now)
    hint = (
        f" Gợi ý giờ trống tiếp theo: {format_local_label(suggestion, schedule.timezone)}."
        if suggestion is not None
        else ""
    )

    if _slot_taken(db, publication, new_at):
        raise RescheduleError(
            "SLOT_COLLISION",
            (
                f"Khung giờ {format_local_label(new_at, schedule.timezone)} đã có "
                f"publication khác trên kênh này.{hint}"
            ),
            409,
        )

    published, scheduled = _daily_usage_excluding_self(
        db, publication, destination, local_day
    )
    if published + scheduled >= schedule.daily_upload_limit:
        raise RescheduleError(
            "DAILY_LIMIT_REACHED",
            (
                f"Ngày {local_day:%d/%m/%Y} đã dùng {published + scheduled}/"
                f"{schedule.daily_upload_limit} lượt đăng (Daily Upload Limit) cho "
                f"kênh này.{hint}"
            ),
            409,
        )

    conflict = _interval_conflict(
        db, publication, new_at, schedule.min_upload_interval_minutes
    )
    if conflict is not None:
        raise RescheduleError(
            "MIN_INTERVAL_VIOLATION",
            (
                f"Thời điểm mới quá gần publication khác trên cùng kênh; cần cách "
                f"nhau ít nhất {schedule.min_upload_interval_minutes} phút.{hint}"
            ),
            409,
        )


def _default_youtube_reschedule(
    db: Session, publication: Publication, new_at: datetime
) -> None:
    from app.youtube import update_video_schedule

    update_video_schedule(
        db, publication.destination_id, publication.external_post_id, new_at
    )


def reschedule_publication(
    db: Session,
    publication: Publication,
    new_at: datetime,
    *,
    timezone_name: str | None = None,
    now: datetime | None = None,
    youtube_rescheduler: Callable[[Session, Publication, datetime], None] | None = None,
) -> Publication:
    """Validate and persist one reschedule atomically. Returns the publication."""
    now_utc = ensure_utc(now or datetime.now(timezone.utc))
    destination = db.get(Destination, publication.destination_id)
    if destination is None:
        raise RescheduleError(
            "DESTINATION_NOT_FOUND",
            "Không tìm thấy destination của publication.",
            status_code=404,
        )
    schedule = _schedule_for(destination)
    tz_name = (timezone_name or schedule.timezone or "Asia/Ho_Chi_Minh").strip()
    target = _normalize_target(new_at, timezone_name)
    validate_reschedule(db, publication, destination, schedule, target, now_utc)

    uploaded, native = youtube_flags(publication)
    if native:
        rescheduler = youtube_rescheduler or _default_youtube_reschedule
        try:
            rescheduler(db, publication, target)
        except RescheduleError:
            raise
        except Exception as exc:  # YouTube API must not be reported as success
            raise RescheduleError(
                "YOUTUBE_RESCHEDULE_FAILED",
                f"YouTube không đổi được lịch: {str(exc)[:500]}",
                status_code=502,
            ) from exc

    previous_at = publication.scheduled_at
    plans = linked_jobs(db, publication)
    live_job = any((job.status or "").lower() != "failed" for job in plans)
    slot_key = f"{destination.id}:{target.isoformat()}"

    publication.scheduled_at = target
    publication.error = None
    publication.status = "scheduled" if live_job else "queued"
    if native:
        publication.youtube_publish_at = target
        publication.youtube_schedule_timezone = tz_name
        publication.youtube_publish_mode = "scheduled"
        publication.youtube_scheduled = True
        publication.youtube_privacy_status = "private"

    for job in plans:
        if (job.status or "").lower() == "failed":
            # Keep failed history intact: never resurrect an upload silently.
            continue
        job.youtube_schedule_timezone = tz_name
        if native:
            job.youtube_publish_at = target
            job.youtube_publish_mode = "scheduled"
        elif job.status == "pending":
            # Release the old reservation and hold the new minute.
            job.schedule_slot_key = slot_key
            job.youtube_publish_at = target

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        suggestion = _next_free_slot(db, publication, destination, now_utc)
        hint = (
            f" Gợi ý giờ trống tiếp theo: {format_local_label(suggestion, schedule.timezone)}."
            if suggestion is not None
            else ""
        )
        raise RescheduleError(
            "SLOT_COLLISION",
            (
                f"Khung giờ {format_local_label(target, schedule.timezone)} vừa bị "
                f"chiếm bởi một job khác.{hint}"
            ),
            409,
        ) from exc
    except Exception:
        db.rollback()
        raise

    db.refresh(publication)
    # SQLite returns naive datetimes after a refresh; the API contract is UTC,
    # so never hand a bare local-looking timestamp back to the dashboard.
    for field in ("scheduled_at", "youtube_publish_at"):
        value = getattr(publication, field, None)
        if value is not None:
            setattr(publication, field, ensure_utc(value))
    return publication
