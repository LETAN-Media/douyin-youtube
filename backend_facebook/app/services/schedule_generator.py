"""Auto Schedule Generator for Facebook Pipelines.

Generates weekly publish schedules based on configurable parameters:
- max_daily_publish (max videos/day)
- start_time / end_time (allowed publish window)
- min_interval_minutes (minimum gap between slots)
- weekdays (which days to schedule)
- distribution_mode (even / peak_hours / channel_stats)
- allow_midnight (allow 00:00-06:00 slots)
- separate_weekend (different config for weekend days)

All times are in the pipeline's timezone (default Asia/Ho_Chi_Minh).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import time, timedelta
from enum import Enum
from typing import Any


class DistributionMode(str, Enum):
    EVEN = "even"
    PEAK_HOURS = "peak_hours"
    CHANNEL_STATS = "channel_stats"


class ScheduleGenerationError(Exception):
    """Raised when schedule generation fails validation."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{code}] {message}")


@dataclass
class ScheduleGenerationConfig:
    """Configuration for schedule generation."""

    max_daily_publish: int
    start_time: str  # HH:MM
    end_time: str  # HH:MM
    min_interval_minutes: int
    weekdays: list[int]  # 0=Monday ... 6=Sunday
    distribution_mode: DistributionMode = DistributionMode.EVEN
    allow_midnight: bool = False
    separate_weekend: bool = False
    weekend_start_time: str | None = None
    weekend_end_time: str | None = None
    weekend_min_interval_minutes: int | None = None
    weekend_max_daily_publish: int | None = None

    def __post_init__(self):
        # Validate time formats
        self._validate_time("start_time", self.start_time)
        self._validate_time("end_time", self.end_time)
        if self.weekend_start_time:
            self._validate_time("weekend_start_time", self.weekend_start_time)
        if self.weekend_end_time:
            self._validate_time("weekend_end_time", self.weekend_end_time)

        # Validate ranges
        if not 1 <= self.max_daily_publish <= 1000:
            raise ScheduleGenerationError(
                "INVALID_MAX_DAILY",
                "max_daily_publish must be between 1 and 1000",
            )
        if not 1 <= self.min_interval_minutes <= 1440:
            raise ScheduleGenerationError(
                "INVALID_INTERVAL",
                "min_interval_minutes must be between 1 and 1440",
            )
        if self.weekend_min_interval_minutes is not None:
            if not 1 <= self.weekend_min_interval_minutes <= 1440:
                raise ScheduleGenerationError(
                    "INVALID_WEEKEND_INTERVAL",
                    "weekend_min_interval_minutes must be between 1 and 1440",
                )
        if self.weekend_max_daily_publish is not None:
            if not 1 <= self.weekend_max_daily_publish <= 1000:
                raise ScheduleGenerationError(
                    "INVALID_WEEKEND_MAX_DAILY",
                    "weekend_max_daily_publish must be between 1 and 1000",
                )
        if not self.weekdays:
            raise ScheduleGenerationError(
                "NO_WEEKDAYS",
                "At least one weekday must be selected",
            )
        if not all(0 <= d <= 6 for d in self.weekdays):
            raise ScheduleGenerationError(
                "INVALID_WEEKDAY",
                "Weekdays must be 0-6 (Monday-Sunday)",
            )

        # Check if schedule is feasible
        self._check_feasibility()

    def _validate_time(self, field: str, value: str) -> None:
        try:
            hour, minute = map(int, value.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except (ValueError, AttributeError):
            raise ScheduleGenerationError(
                "INVALID_TIME_FORMAT",
                f"{field} must be HH:MM format (00:00-23:59)",
            )

    def _check_feasibility(self) -> None:
        """Check if the configuration can produce enough slots."""
        for day in self.weekdays:
            is_weekend = day >= 5
            max_daily = (
                self.weekend_max_daily_publish
                if is_weekend and self.separate_weekend and self.weekend_max_daily_publish
                else self.max_daily_publish
            )
            start = self._get_start_time(day)
            end = self._get_end_time(day)
            interval = (
                self.weekend_min_interval_minutes
                if is_weekend and self.separate_weekend and self.weekend_min_interval_minutes
                else self.min_interval_minutes
            )

            feasible = self._count_feasible_slots(start, end, interval)
            if feasible < max_daily:
                day_name = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][day]
                raise ScheduleGenerationError(
                    "INSUFFICIENT_WINDOW",
                    (
                        f"Day {day_name}: Cannot fit {max_daily} videos in window "
                        f"{start}-{end} with {interval}min interval. "
                        f"Max feasible: {feasible}. "
                        f"Reduce max_daily_publish, extend window, or reduce interval."
                    ),
                    details={
                        "day": day,
                        "max_daily": max_daily,
                        "feasible": feasible,
                        "window": f"{start}-{end}",
                        "interval": interval,
                    },
                )

    def _get_start_time(self, day: int) -> str:
        if day >= 5 and self.separate_weekend and self.weekend_start_time:
            return self.weekend_start_time
        return self.start_time

    def _get_end_time(self, day: int) -> str:
        if day >= 5 and self.separate_weekend and self.weekend_end_time:
            return self.weekend_end_time
        return self.end_time

    def _count_feasible_slots(self, start: str, end: str, interval: int) -> int:
        """Count how many slots fit in the time window with given interval."""
        sh, sm = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
        start_minutes = sh * 60 + sm
        end_minutes = eh * 60 + em
        if end_minutes <= start_minutes:
            return 0
        # Number of intervals that fit: (window - 1) // interval + 1
        # But we need at least 1 slot
        return max(1, (end_minutes - start_minutes) // interval + 1)


@dataclass
class GeneratedSlot:
    """A single generated time slot."""

    weekday: int  # 0=Monday ... 6=Sunday
    time: str  # HH:MM
    is_weekend: bool = False


@dataclass
class GenerationResult:
    """Result of schedule generation."""

    slots: list[GeneratedSlot]
    warnings: list[str]
    feasibility_report: dict[str, Any]


# Peak hours for Vietnam/Asia (when engagement is typically highest)
PEAK_HOURS_MORNING = [(7, 9), (11, 13)]
PEAK_HOURS_AFTERNOON = [(17, 20)]
PEAK_HOURS_WEEKEND = [(9, 11), (14, 16), (19, 21)]


def _time_to_minutes(t: str) -> int:
    h, m = map(int, t.split(":"))
    return h * 60 + m


def _minutes_to_time(m: int) -> str:
    h = m // 60
    m = m % 60
    return f"{h:02d}:{m:02d}"


AUTO_SLOT_START = "09:00"
AUTO_SLOT_END = "22:30"
MINUTES_PER_DAY = 24 * 60


def _distribute_day_slots(
    max_daily: int,
    current_times: list[str],
    fallback_start: int,
    fallback_end: int,
) -> list[str]:
    if max_daily <= 0:
        return []

    minutes: list[int] = []
    for value in current_times:
        try:
            minutes.append(_time_to_minutes(value))
        except (ValueError, AttributeError):
            continue
    minutes.sort()

    start = minutes[0] if len(minutes) >= 2 else fallback_start
    end = minutes[-1] if len(minutes) >= 2 else fallback_end
    if end <= start:
        start, end = fallback_start, fallback_end
    if end <= start:
        return []

    if max_daily == 1:
        return [_minutes_to_time(start)]

    span = end - start
    if max_daily > span + 1:
        return [
            _minutes_to_time((index * MINUTES_PER_DAY) // max_daily)
            for index in range(max_daily)
        ]

    return [
        _minutes_to_time(math.floor(start + (span * index) / (max_daily - 1) + 0.5))
        for index in range(max_daily)
    ]


def generate_auto_slots(
    max_daily_publish: int,
    existing_slots: dict[int, list[str]] | None = None,
) -> dict[int, list[str]]:
    """Distribute max_daily_publish slots evenly across the current day windows."""
    existing = existing_slots or {}
    all_minutes: list[int] = []
    for times in existing.values():
        for value in times:
            try:
                all_minutes.append(_time_to_minutes(value))
            except (ValueError, AttributeError):
                continue

    fallback_start = (
        min(all_minutes) if len(all_minutes) >= 2 else _time_to_minutes(AUTO_SLOT_START)
    )
    fallback_end = (
        max(all_minutes) if len(all_minutes) >= 2 else _time_to_minutes(AUTO_SLOT_END)
    )

    return {
        day: _distribute_day_slots(
            max_daily_publish,
            list(existing.get(day, [])),
            fallback_start,
            fallback_end,
        )
        for day in range(7)
    }


def _is_in_peak_hours(hour: int, is_weekend: bool) -> bool:
    """Check if an hour falls in peak engagement hours."""
    if is_weekend:
        for start, end in PEAK_HOURS_WEEKEND:
            if start <= hour < end:
                return True
    else:
        for start, end in PEAK_HOURS_MORNING:
            if start <= hour < end:
                return True
        for start, end in PEAK_HOURS_AFTERNOON:
            if start <= hour < end:
                return True
    return False


def _generate_even_slots(
    start_min: int,
    end_min: int,
    max_slots: int,
    min_interval: int,
    is_weekend: bool,
) -> list[int]:
    """Generate evenly distributed slots."""
    if max_slots <= 1:
        return [start_min]
    available = end_min - start_min
    if available < min_interval * (max_slots - 1):
        # Not enough space, pack as many as possible at even spacing
        actual_interval = available // (max_slots - 1) if max_slots > 1 else available
        actual_interval = max(actual_interval, min_interval)
    else:
        actual_interval = min_interval

    slots = []
    for i in range(max_slots):
        slot_min = start_min + i * actual_interval
        if slot_min <= end_min:
            slots.append(slot_min)
    return slots[:max_slots]


def _generate_peak_hours_slots(
    start_min: int,
    end_min: int,
    max_slots: int,
    min_interval: int,
    is_weekend: bool,
) -> list[int]:
    """Generate slots preferring peak engagement hours."""
    # First, identify peak hour minutes
    peak_minutes = []
    for h in range(start_min // 60, end_min // 60 + 1):
        if _is_in_peak_hours(h, is_weekend):
            peak_minutes.extend(range(h * 60, min((h + 1) * 60, end_min + 1)))

    # Filter peak minutes to valid range
    peak_minutes = [m for m in peak_minutes if start_min <= m <= end_min]

    if not peak_minutes:
        # Fall back to even distribution
        return _generate_even_slots(start_min, end_min, max_slots, min_interval, is_weekend)

    # Select from peak minutes first
    slots = []
    # Try to pick from peak minutes with min_interval spacing
    last = -min_interval - 1
    for m in sorted(peak_minutes):
        if m - last >= min_interval and len(slots) < max_slots:
            slots.append(m)
            last = m

    # If still need more slots, fill with even distribution in remaining space
    if len(slots) < max_slots:
        remaining = max_slots - len(slots)
        # Find gaps
        all_minutes = set(range(start_min, end_min + 1, min_interval))
        available = sorted(all_minutes - set(slots))
        for m in available:
            if len(slots) >= max_slots:
                break
            # Check interval constraint
            if all(abs(m - s) >= min_interval for s in slots):
                slots.append(m)

    return sorted(slots)[:max_slots]


def generate_weekly_schedule(config: ScheduleGenerationConfig) -> GenerationResult:
    """Generate a complete weekly schedule based on configuration."""
    all_slots: list[GeneratedSlot] = []
    warnings: list[str] = []
    feasibility_report: dict[str, Any] = {}

    for day in sorted(config.weekdays):
        is_weekend = day >= 5
        max_daily = (
            config.weekend_max_daily_publish
            if is_weekend and config.separate_weekend and config.weekend_max_daily_publish
            else config.max_daily_publish
        )
        start = config._get_start_time(day)
        end = config._get_end_time(day)
        interval = (
            config.weekend_min_interval_minutes
            if is_weekend and config.separate_weekend and config.weekend_min_interval_minutes
            else config.min_interval_minutes
        )

        start_min = _time_to_minutes(start)
        end_min = _time_to_minutes(end)

        if end_min <= start_min:
            warnings.append(
                f"Day {day}: end_time ({end}) <= start_time ({start}), skipping"
            )
            feasibility_report[day] = {
                "max_daily": max_daily,
                "generated": 0,
                "warning": "Invalid window",
            }
            continue

        # Check midnight restriction
        if not config.allow_midnight:
            # Exclude 00:00-06:00
            midnight_end = 6 * 60
            if start_min < midnight_end:
                start_min = max(start_min, midnight_end)
                if start_min >= end_min:
                    warnings.append(
                        f"Day {day}: Window {start}-{end} fully in midnight (00:00-06:00), skipping"
                    )
                    feasibility_report[day] = {
                        "max_daily": max_daily,
                        "generated": 0,
                        "warning": "Window in restricted hours",
                    }
                    continue

        # Generate slots based on distribution mode
        if config.distribution_mode == DistributionMode.PEAK_HOURS:
            slot_minutes = _generate_peak_hours_slots(
                start_min, end_min, max_daily, interval, is_weekend
            )
        else:
            slot_minutes = _generate_even_slots(
                start_min, end_min, max_daily, interval, is_weekend
            )

        # Create slot objects
        day_slots = [
            GeneratedSlot(weekday=day, time=_minutes_to_time(m), is_weekend=is_weekend)
            for m in slot_minutes
        ]
        all_slots.extend(day_slots)

        feasible = _count_feasible(start_min, end_min, interval)
        feasibility_report[day] = {
            "max_daily": max_daily,
            "generated": len(day_slots),
            "window": f"{start}-{end}",
            "interval": interval,
            "feasible": feasible,
            "distribution_mode": config.distribution_mode.value,
        }

        if len(day_slots) < max_daily:
            warnings.append(
                f"Day {day}: Requested {max_daily} slots but only {len(day_slots)} fit "
                f"in {start}-{end} with {interval}min interval"
            )

    return GenerationResult(
        slots=all_slots,
        warnings=warnings,
        feasibility_report=feasibility_report,
    )


def _count_feasible(start_min: int, end_min: int, interval: int) -> int:
    """Count how many slots fit in window with interval."""
    if end_min <= start_min:
        return 0
    return max(1, (end_min - start_min) // interval + 1)


def slots_to_dict(slots: list[GeneratedSlot]) -> dict[str, list[str]]:
    """Convert generated slots to the format used by the API (weekday name -> list of times)."""
    weekday_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    result: dict[str, list[str]] = {name: [] for name in weekday_names}
    for slot in slots:
        day_name = weekday_names[slot.weekday]
        result[day_name].append(slot.time)
    # Sort times within each day
    for times in result.values():
        times.sort()
    return result


def dict_to_slots(slots_dict: dict[str, list[str]]) -> list[GeneratedSlot]:
    """Convert API format slots to GeneratedSlot list."""
    weekday_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    name_to_idx = {name: idx for idx, name in enumerate(weekday_names)}
    result = []
    for day_name, times in slots_dict.items():
        if day_name in name_to_idx:
            for t in times:
                result.append(GeneratedSlot(weekday=name_to_idx[day_name], time=t, is_weekend=name_to_idx[day_name] >= 5))
    return result


def preview_generated_schedule(config_dict: dict[str, Any]) -> dict[str, Any]:
    """Generate a preview of the schedule without saving."""
    try:
        # Convert distribution_mode string to enum if needed
        config_data = dict(config_dict)
        if "distribution_mode" in config_data and isinstance(config_data["distribution_mode"], str):
            config_data["distribution_mode"] = DistributionMode(config_data["distribution_mode"])
        config = ScheduleGenerationConfig(**config_data)
        result = generate_weekly_schedule(config)
        return {
            "ok": True,
            "slots": slots_to_dict(result.slots),
            "warnings": result.warnings,
            "feasibility_report": result.feasibility_report,
        }
    except ScheduleGenerationError as e:
        return {
            "ok": False,
            "error": e.code,
            "message": e.message,
            "details": e.details,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": "GENERATION_FAILED",
            "message": str(e),
        }