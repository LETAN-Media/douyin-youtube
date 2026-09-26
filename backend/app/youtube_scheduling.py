"""Native YouTube Scheduled Publishing helpers.

Single source of truth for:
- publish modes: immediate | scheduled | private | unlisted
- timezone-aware local -> UTC RFC3339 conversion (DST-safe via zoneinfo)
- validation (future datetime + safety margin)
- status payload building for videos.insert / videos.update
- per-channel auto slot assignment with collision protection
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger("douyin-youtube-scheduling")

PUBLISH_MODES = ("immediate", "scheduled", "private", "unlisted")

# Minimum future margin for a scheduled publish (YouTube rejects past times
# and may publish immediately if the time is too close).
SCHEDULE_MIN_MARGIN = timedelta(minutes=5)

DEFAULT_SCHEDULE_TIMEZONE = "Asia/Ho_Chi_Minh"

# Map publish_mode -> YouTube privacyStatus used on INSERT.
MODE_TO_PRIVACY = {
    "immediate": "public",
    "scheduled": "private",  # REQUIRED: publishAt only valid with private
    "private": "private",
    "unlisted": "unlisted",
}


class ScheduleValidationError(ValueError):
    code = "INVALID_PUBLISH_AT"


def resolve_timezone(tz_name: str | None) -> ZoneInfo:
    name = (tz_name or DEFAULT_SCHEDULE_TIMEZONE).strip() or DEFAULT_SCHEDULE_TIMEZONE
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        logger.warning("Unknown timezone %r, falling back to %s", tz_name, DEFAULT_SCHEDULE_TIMEZONE)
        try:
            return ZoneInfo(DEFAULT_SCHEDULE_TIMEZONE)
        except Exception:
            return ZoneInfo("UTC")  # type: ignore[return-value]


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def local_to_utc(
    date_str: str,
    time_str: str,
    tz_name: str | None,
) -> datetime:
    """Convert UI local date+time+timezone to canonical UTC datetime.

    DST-safe: uses zoneinfo, never manual +/- arithmetic.
    Accepts date 'YYYY-MM-DD' or 'DD/MM/YYYY', time 'HH:MM' (24h).
    """
    tz = resolve_timezone(tz_name)
    date_str = (date_str or "").strip()
    time_str = (time_str or "").strip()
    # Support DD/MM/YYYY (spec example 26/09/2026)
    dt_local: datetime | None = None
    for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M"):
        try:
            naive = datetime.strptime(f"{date_str} {time_str}", fmt)
            dt_local = naive.replace(tzinfo=tz)
            break
        except ValueError:
            continue
    if dt_local is None:
        raise ScheduleValidationError(
            f"INVALID_PUBLISH_AT: cannot parse date={date_str!r} time={time_str!r}"
        )
    return dt_local.astimezone(timezone.utc)


def parse_publish_at(value: datetime | str | None, tz_name: str | None = None) -> datetime | None:
    """Normalize various publish_at inputs to UTC aware datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            # Naive datetimes are interpreted in the given timezone.
            tz = resolve_timezone(tz_name)
            dt = dt.replace(tzinfo=tz)
        return dt.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    # Try ISO8601 first.
    try:
        iso = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            tz = resolve_timezone(tz_name)
            dt = dt.replace(tzinfo=tz)
        return dt.astimezone(timezone.utc)
    except ValueError:
        raise ScheduleValidationError(f"INVALID_PUBLISH_AT: cannot parse {text!r}")


def validate_publish_at(publish_at_utc: datetime, now: datetime | None = None) -> datetime:
    """Ensure publish_at is in the future with safety margin. Returns UTC."""
    now_utc = ensure_utc(now or datetime.now(timezone.utc))
    pub = ensure_utc(publish_at_utc)
    if pub <= now_utc + SCHEDULE_MIN_MARGIN:
        raise ScheduleValidationError(
            "INVALID_PUBLISH_AT: publish_at must be at least 5 minutes in the future"
        )
    return pub


def validate_scheduled_mode(publish_mode: str, publish_at_utc: datetime | None, now: datetime | None = None) -> datetime | None:
    mode = (publish_mode or "immediate").lower()
    if mode not in PUBLISH_MODES:
        raise ScheduleValidationError(f"INVALID_PUBLISH_MODE: {publish_mode!r}")
    if mode == "scheduled":
        if publish_at_utc is None:
            raise ScheduleValidationError("INVALID_PUBLISH_AT: scheduled mode requires publish_at")
        return validate_publish_at(publish_at_utc, now=now)
    return None


def to_rfc3339_utc(dt: datetime) -> str:
    """YouTube expects RFC3339, e.g. 2026-09-26T12:30:00Z."""
    utc = ensure_utc(dt)
    # Drop microseconds for API stability.
    utc = utc.replace(microsecond=0)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_insert_status(publish_mode: str, publish_at_utc: datetime | None = None) -> dict:
    """Status body for videos.insert."""
    mode = (publish_mode or "immediate").lower()
    if mode not in PUBLISH_MODES:
        raise ScheduleValidationError(f"INVALID_PUBLISH_MODE: {publish_mode!r}")
    privacy = MODE_TO_PRIVACY[mode]
    status: dict = {"privacyStatus": privacy}
    if mode == "scheduled":
        if publish_at_utc is None:
            raise ScheduleValidationError("INVALID_PUBLISH_AT: scheduled requires publish_at")
        # publishAt only valid when privacyStatus == private.
        status["publishAt"] = to_rfc3339_utc(publish_at_utc)
    # Never send publishAt for public/unlisted/private.
    return status


def build_reschedule_status(new_publish_at_utc: datetime) -> dict:
    """Status body for videos.update change-time. MUST include private."""
    return {"privacyStatus": "private", "publishAt": to_rfc3339_utc(new_publish_at_utc)}


def build_publish_now_status() -> dict:
    return {"privacyStatus": "public"}


def normalize_youtube_error(exc: Exception) -> str:
    """Extract normalized code + message for DB storage."""
    text = str(exc)
    lowered = text.lower()
    for code in ("invalidpublishat", "invalid_publish_at", "forbiddenprivacysetting", "forbidden_privacy"):
        if code.replace("_", "") in lowered.replace("_", "").replace(" ", ""):
            # Return canonical snake form.
            if "publishat" in code:
                return f"invalidPublishAt: {text[:1000]}"
            return f"forbiddenPrivacySetting: {text[:1000]}"
    # Also catch "publishAt" / "privacy" mentions generically.
    if "publishat" in lowered:
        return f"invalidPublishAt: {text[:1000]}"
    return text[:2000]


def format_scheduled_preview(publish_at_utc: datetime, tz_name: str | None) -> str:
    """UI preview e.g. 'Scheduled: 26 Sep 2026, 19:30 GMT+7'."""
    tz = resolve_timezone(tz_name)
    local = ensure_utc(publish_at_utc).astimezone(tz)
    # GMT offset label.
    offset = local.utcoffset() or timedelta(0)
    hours = int(offset.total_seconds() // 3600)
    label = f"GMT+{hours}" if hours >= 0 else f"GMT{hours}"
    return f"Scheduled: {local.strftime('%d %b %Y, %H:%M')} {label}"


# ---------------------------------------------------------------------------
# Auto slot assignment (per-channel, collision-protected)
# ---------------------------------------------------------------------------

def _slot_datetimes_for_day(day, slots: list[str], tz: ZoneInfo) -> list[datetime]:
    out: list[datetime] = []
    for s in slots or []:
        try:
            h, m = map(int, str(s).strip().split(":"))
            local = datetime.combine(day, datetime.min.time().replace(hour=h, minute=m)).replace(tzinfo=tz)
            out.append(local.astimezone(timezone.utc))
        except (ValueError, TypeError):
            continue
    return sorted(out)


def find_next_free_slot(
    slots: list[str],
    tz_name: str | None,
    used_utc_slots: set[str],
    now: datetime | None = None,
    max_days: int = 30,
    allow_collision: bool = False,
) -> datetime | None:
    """Find nearest future slot (UTC) not already used.

    used_utc_slots: set of ISO strings (minute precision) already taken.
    Never assigns 2 videos to the same slot unless allow_collision=True.
    """
    now_utc = ensure_utc(now or datetime.now(timezone.utc))
    tz = resolve_timezone(tz_name)
    # Normalize used set to minute precision ISO.
    used_norm = set()
    for u in used_utc_slots or set():
        try:
            dt = parse_publish_at(u) if isinstance(u, str) else ensure_utc(u)
            if dt is not None:
                used_norm.add(ensure_utc(dt).replace(second=0, microsecond=0).isoformat())
        except Exception:
            continue
    local_now = now_utc.astimezone(tz)
    for day_offset in range(max_days + 1):
        day = (local_now + timedelta(days=day_offset)).date()
        for slot_utc in _slot_datetimes_for_day(day, slots or [], tz):
            if slot_utc <= now_utc + SCHEDULE_MIN_MARGIN:
                continue
            key = slot_utc.replace(second=0, microsecond=0).isoformat()
            if key in used_norm and not allow_collision:
                continue
            return slot_utc.replace(second=0, microsecond=0)
    return None


def assign_backlog_slots(
    count: int,
    slots: list[str],
    tz_name: str | None,
    used_utc_slots: set[str],
    start_after: datetime | None = None,
    allow_collision: bool = False,
) -> list[datetime]:
    """Assign N sequential free slots (e.g. 20 videos over 09:00/18:00)."""
    assigned: list[datetime] = []
    used = set(used_utc_slots or set())
    cursor = ensure_utc(start_after or datetime.now(timezone.utc))
    for _ in range(count):
        nxt = find_next_free_slot(slots, tz_name, used, now=cursor, allow_collision=allow_collision)
        if nxt is None:
            break
        assigned.append(nxt)
        used.add(nxt.isoformat())
        cursor = nxt + timedelta(minutes=1)
    return assigned
