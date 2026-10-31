"""One schedule contract for settings, previews, scheduler and worker."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings


class ScheduleError(ValueError):
    pass


def minute(value: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r'\d{2}:\d{2}', value):
        raise ScheduleError(f'Invalid time {value!r}; expected HH:MM')
    h, m = map(int, value.split(':'))
    if h > 23 or m > 59:
        raise ScheduleError(f'Invalid time {value!r}')
    return h * 60 + m


def generate_slots(count: int, start='08:00', end='23:00', overnight=False, minimum=1):
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ScheduleError('Daily Upload Limit must be a positive integer')
    if count > settings.scheduler_max_daily_uploads:
        raise ScheduleError(f'Daily limit {count} exceeds configured safety limit {settings.scheduler_max_daily_uploads}')
    a, b = minute(start), minute(end)
    if b < a:
        if not overnight:
            raise ScheduleError('End precedes start; explicitly enable overnight publishing')
        b += 1440
    elif overnight:
        raise ScheduleError('Overnight publishing requires End Time before Start Time')
    minimum = max(settings.scheduler_min_slot_interval_minutes, minimum)
    if count > 1 and (b - a) // (count - 1) < minimum:
        raise ScheduleError(f'{count} slots do not fit {start}–{end} with minimum interval {minimum} minutes')
    values = [a] if count == 1 else [a + (i * (b - a) + (count - 1)//2)//(count - 1) for i in range(count)]
    if len(set(v % 1440 for v in values)) != count:
        raise ScheduleError('Publishing window produces duplicate times')
    return [f'{v % 1440 // 60:02d}:{v % 60:02d}' for v in values]


SCHEDULE_FIELDS = {
    'daily_upload_limit', 'upload_slots', 'timezone', 'publishing_start_time',
    'publishing_end_time', 'auto_distribute_upload_slots', 'publishing_overnight',
    'min_upload_interval_minutes', 'backlog_slots_per_day', 'new_slots_per_day',
    'slot_fallback_enabled', 'schedule_override_enabled',
}


@dataclass(frozen=True)
class EffectiveSchedule:
    daily_upload_limit: int
    upload_slots: list[str]
    timezone: str
    publishing_start_time: str
    publishing_end_time: str
    auto_distribute_upload_slots: bool
    publishing_overnight: bool
    min_upload_interval_minutes: int
    backlog_slots_per_day: int
    new_slots_per_day: int
    slot_fallback_enabled: bool
    source: str
    warnings: list[str]

    def to_dict(self):
        return asdict(self)


def effective_schedule(destination=None, pipeline=None):
    if pipeline is None and destination is not None:
        pipeline = getattr(destination, 'pipeline', None)
    override = getattr(destination, 'schedule_override_enabled', None)
    # Migration preserves independent legacy schedules explicitly. Unpersisted
    # destination-only callers still use their own settings when no parent exists.
    owner = destination if destination is not None and (override is True or pipeline is None) else pipeline
    def value(name, default):
        v = getattr(owner, name, None)
        return default if v is None else v
    limit = value('daily_upload_limit', settings.youtube_shorts_daily_limit)
    auto = value('auto_distribute_upload_slots', False)
    start, end = value('publishing_start_time', '08:00'), value('publishing_end_time', '23:00')
    overnight = value('publishing_overnight', False)
    interval = max(settings.scheduler_min_slot_interval_minutes, value('min_upload_interval_minutes', 1))
    # Validate even legacy settings; never silently clamp a configured limit.
    raw = value('upload_slots', None)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= settings.scheduler_max_daily_uploads:
        raise ScheduleError(f'Daily Upload Limit must be a positive integer up to configured safety limit {settings.scheduler_max_daily_uploads}')
    generated = generate_slots(limit if auto or not raw else len(raw), start, end, overnight, interval)
    slots = generated if auto else (raw or generated)
    if len(set(slots)) != len(slots):
        raise ScheduleError('Upload slots must be unique')
    for slot in slots:
        minute(slot)
    anchor = minute(start)
    slots = sorted(slots, key=lambda s: (minute(s)-anchor) % 1440 if overnight else minute(s))
    tz = value('timezone', 'UTC')
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ScheduleError(f'Unknown timezone: {tz}')
    backlog, new = value('backlog_slots_per_day', 0), value('new_slots_per_day', 0)
    if backlog + new != limit:
        backlog = (limit * backlog + (backlog + new)//2)//(backlog + new) if backlog + new else 0
        new = limit - backlog
    warnings = []
    if len(slots) != limit:
        warnings.append(f'Legacy manual schedule has {len(slots)} slots for daily limit {limit}; save a matching schedule')
    if limit >= settings.scheduler_daily_upload_warning_threshold:
        warnings.append(f'High daily upload count ({limit}); verify YouTube project quota and source inventory')
    return EffectiveSchedule(limit, slots, tz, start, end, auto, overnight, interval, backlog, new,
                             value('slot_fallback_enabled', True), 'destination' if owner is destination else 'pipeline', warnings)


def prepare_schedule_update(owner, data, pipeline=None):
    """Validate a complete merged settings update without touching existing jobs."""
    from types import SimpleNamespace
    if not (set(data) & SCHEDULE_FIELDS):
        return data
    merged = {name: getattr(owner, name, None) for name in SCHEDULE_FIELDS}
    merged.update(data)
    # Schedule writes through destination endpoints require an explicit override.
    if pipeline is not None and not merged.get('schedule_override_enabled'):
        if set(data) & (SCHEDULE_FIELDS - {'schedule_override_enabled'}):
            raise ScheduleError('Enable Destination schedule override before editing its schedule, or edit Pipeline Settings')
        if merged.get('schedule_override_enabled') != getattr(owner, 'schedule_override_enabled', None):
            data['schedule_updated_at'] = datetime.now(timezone.utc)
        return data
    minimum = merged.get('min_upload_interval_minutes')
    if minimum is not None and minimum < settings.scheduler_min_slot_interval_minutes:
        raise ScheduleError(f'Minimum interval must be at least {settings.scheduler_min_slot_interval_minutes} minute(s)')
    target = SimpleNamespace(**merged)
    schedule = effective_schedule(target)
    budget = settings.youtube_project_daily_upload_budget
    if budget and schedule.daily_upload_limit > budget:
        raise ScheduleError(f'Daily limit {schedule.daily_upload_limit} exceeds the configured YouTube project upload budget {budget}; change the budget or choose a feasible limit')
    if schedule.auto_distribute_upload_slots:
        data['upload_slots'] = schedule.upload_slots
    elif len(schedule.upload_slots) != schedule.daily_upload_limit:
        raise ScheduleError(f'Manual schedule must have exactly {schedule.daily_upload_limit} unique slots; found {len(schedule.upload_slots)}')
    a, b = minute(schedule.publishing_start_time), minute(schedule.publishing_end_time)
    if schedule.publishing_overnight:
        b += 1440
    times = [minute(s) + (1440 if schedule.publishing_overnight and minute(s) < a else 0) for s in schedule.upload_slots]
    if any(t < a or t > b for t in times):
        raise ScheduleError('Upload slots must stay inside the publishing window')
    times.sort()
    if any(y-x < schedule.min_upload_interval_minutes for x,y in zip(times,times[1:])):
        raise ScheduleError(f'Upload slots require at least {schedule.min_upload_interval_minutes} minutes spacing')
    # Also protect the boundary between adjacent publishing days.
    if len(times)>1 and 1440-times[-1]+times[0] < schedule.min_upload_interval_minutes:
        raise ScheduleError('Last and first slots of adjacent days are too close')
    if 'backlog_slots_per_day' in data or 'new_slots_per_day' in data:
        backlog, new = merged.get('backlog_slots_per_day') or 0, merged.get('new_slots_per_day') or 0
        if backlog + new != schedule.daily_upload_limit:
            raise ScheduleError('Backlog + New slots must equal Daily Upload Limit')
    data['backlog_slots_per_day'] = schedule.backlog_slots_per_day
    data['new_slots_per_day'] = schedule.new_slots_per_day
    if any(value != getattr(owner, name, None) for name, value in data.items() if name in SCHEDULE_FIELDS):
        data['schedule_updated_at'] = datetime.now(timezone.utc)
    return data


def schedule_for_display(destination=None, pipeline=None):
    """Keep invalid legacy settings editable, while the scheduler fails closed."""
    try:
        return effective_schedule(destination, pipeline).to_dict()
    except ScheduleError as exc:
        parent = pipeline or (getattr(destination, 'pipeline', None) if destination else None)
        owner = destination if destination is not None and (getattr(destination, 'schedule_override_enabled', False) or parent is None) else parent
        result = {name: getattr(owner, name, None) for name in SCHEDULE_FIELDS if name != 'schedule_override_enabled'}
        result.update(error=str(exc), warnings=[f'INVALID_SCHEDULE: {exc}'], source='destination' if owner is destination else 'pipeline')
        return result
