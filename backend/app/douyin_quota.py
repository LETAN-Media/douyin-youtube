"""Global RapidAPI quota guard for the Douyin creator feed.

Why this exists
---------------
RapidAPI's BASIC plan for "Douyin/China Tiktok All API" is billed per request
and *every feed page is one request*.  A creator with 63 videos is ~3 requests,
not one, and the whole subscription only has ~20 a month.  So the dangerous
operation is not a single call, it is a loop — an initial import that keeps
paging, or a scan that runs on a schedule.

This module is the single place that answers "may I spend another request?".
It keeps one running record for the whole subscription (headers are per-key,
shared by every source), reconciles it against RapidAPI's own headers when they
are present, and refuses to spend past the configured safety floor.

The record lives in `app_settings` so it survives restarts and is shared by the
API process and any background thread.

Nothing here ever logs or returns the RapidAPI key.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import AppSetting

logger = logging.getLogger("douyin-youtube-quota")

#: app_settings key holding the running quota record.
QUOTA_KEY = "rapidapi_quota_state"

STATUS_OK = "ok"
STATUS_LOW = "low"
STATUS_EXHAUSTED = "quota_exhausted"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def month_key(moment: datetime | None = None) -> str:
    """Billing window key, e.g. "2026-09"."""
    moment = moment or utcnow()
    return f"{moment.year:04d}-{moment.month:02d}"


class QuotaExhausted(RuntimeError):
    """Raised when a request must not be spent. Never retried blindly."""


def _int_setting(name: str, default: int) -> int:
    try:
        value = int(getattr(settings, name, default) or default)
    except (TypeError, ValueError):
        value = default
    return max(0, value)


def monthly_limit() -> int:
    """Configured fallback limit, used only when RapidAPI sends no header."""
    return _int_setting("rapidapi_monthly_request_limit", 20)


def safety_margin() -> int:
    return _int_setting("rapidapi_quota_safety_margin", 1)


def _blank_state() -> dict[str, Any]:
    limit = monthly_limit()
    return {
        "month": month_key(),
        "limit": limit,
        "remaining": limit,
        "used": 0,
        "reset_at": None,
        "exhausted": False,
        "source": "local",
        "last_error": None,
        "updated_at": utcnow().isoformat(),
    }


def _load() -> dict[str, Any]:
    """Read the stored record, rolling it over when the month changes."""
    with SessionLocal() as db:
        row = db.get(AppSetting, QUOTA_KEY)
        raw = row.value if row is not None else None

    state: dict[str, Any]
    if not raw:
        state = _blank_state()
    else:
        try:
            parsed = json.loads(raw)
            state = parsed if isinstance(parsed, dict) else _blank_state()
        except (TypeError, ValueError):
            state = _blank_state()

    if state.get("month") != month_key():
        # A new billing window: RapidAPI resets the counter, so we do too.
        previous = state.get("month")
        state = _blank_state()
        logger.info("RapidAPI quota window rolled over from %s", previous)
        _save(state)

    state.setdefault("limit", monthly_limit())
    state.setdefault("remaining", state["limit"])
    state.setdefault("used", max(0, int(state["limit"]) - int(state["remaining"])))
    return state


def _save(state: dict[str, Any]) -> dict[str, Any]:
    state["updated_at"] = utcnow().isoformat()
    payload = json.dumps(state)
    with SessionLocal() as db:
        row = db.get(AppSetting, QUOTA_KEY)
        if row is None:
            db.add(AppSetting(key=QUOTA_KEY, value=payload))
        else:
            row.value = payload
        db.commit()
    return state


def snapshot() -> dict[str, Any]:
    """Public view for the UI. Contains no secrets."""
    state = _load()
    limit = int(state.get("limit") or 0)
    remaining = int(state.get("remaining") or 0)
    if limit <= 0:
        status = STATUS_OK
    elif remaining <= 0:
        status = STATUS_EXHAUSTED
    elif remaining <= safety_margin():
        status = STATUS_LOW
    else:
        status = STATUS_OK
    return {
        "limit": limit,
        "remaining": remaining,
        "used": max(0, int(state.get("used") or (limit - remaining))),
        "month": state.get("month"),
        "reset_at": state.get("reset_at"),
        "status": status,
        "exhausted": bool(state.get("exhausted")) or remaining <= 0,
        "source": state.get("source"),
        "last_error": state.get("last_error"),
        "updated_at": state.get("updated_at"),
    }


def can_spend(requests: int = 1) -> bool:
    """True when `requests` more calls stay above the safety floor.

    `requests` is the number of pages a caller is about to walk, so a refresh
    that might page twice can ask about 2 up front and be refused rather than
    stopping half-way.
    """
    snap = snapshot()
    if snap["limit"] <= 0:
        return True
    return snap["remaining"] - max(1, int(requests)) >= safety_margin()


def ensure_can_spend(requests: int = 1) -> None:
    """Raise QuotaExhausted instead of spending past the floor."""
    if can_spend(requests):
        return
    snap = snapshot()
    raise QuotaExhausted(
        "RAPIDAPI_QUOTA_EXHAUSTED: "
        f"remaining={snap['remaining']}/{snap['limit']} "
        f"(safety margin {safety_margin()}). "
        "Hết quota RapidAPI tháng này — không gọi thêm request nào."
    )


def note_local_spend(requests: int = 1) -> dict[str, Any]:
    """Account for requests the API did not report headers for."""
    state = _load()
    state["used"] = int(state.get("used") or 0) + max(1, int(requests))
    if state.get("limit"):
        state["remaining"] = max(0, int(state["limit"]) - int(state["used"]))
    state["source"] = "local"
    return _save(state)


def record_headers(headers: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Reconcile with RapidAPI's authoritative rate-limit headers.

    Returns the updated snapshot, or None when the response carried no quota
    headers at all (then the caller falls back to `note_local_spend`).
    """
    if not headers:
        return None
    limit_raw = headers.get("x-ratelimit-requests-limit")
    remaining_raw = headers.get("x-ratelimit-requests-remaining")
    reset_raw = headers.get("x-ratelimit-requests-reset")
    if limit_raw is None and remaining_raw is None:
        return None

    state = _load()

    def _as_int(value: Any) -> int | None:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    limit = _as_int(limit_raw)
    remaining = _as_int(remaining_raw)
    if limit is not None:
        state["limit"] = limit
    if remaining is not None:
        state["remaining"] = remaining
    resolved_limit = int(state.get("limit") or 0)
    resolved_remaining = int(state.get("remaining") or 0)
    state["used"] = max(0, resolved_limit - resolved_remaining) if resolved_limit else int(
        state.get("used") or 0
    )
    if reset_raw is not None:
        state["reset_at"] = str(reset_raw)
    state["source"] = "header"
    state["exhausted"] = resolved_limit > 0 and resolved_remaining <= 0
    if state["exhausted"]:
        state["last_error"] = "RapidAPI monthly quota exhausted"
    _save(state)
    return snapshot()


def mark_exhausted(message: str | None = None) -> dict[str, Any]:
    """Record a hard 429 / code 303 without retrying."""
    state = _load()
    state["remaining"] = 0
    state["used"] = int(state.get("limit") or state.get("used") or 0)
    state["exhausted"] = True
    state["source"] = "header"
    state["last_error"] = (message or "RapidAPI monthly quota exhausted")[:500]
    _save(state)
    return snapshot()


def note_provider_error(message: str | None = None) -> None:
    """Record a non-quota failure so the UI can show why a scan stopped."""
    state = _load()
    state["last_error"] = (message or "")[:500]
    _save(state)


def reset_for_tests() -> None:
    """Clear the stored record (used by tests only)."""
    with SessionLocal() as db:
        row = db.get(AppSetting, QUOTA_KEY)
        if row is not None:
            db.delete(row)
            db.commit()


__all__ = [
    "QUOTA_KEY",
    "STATUS_EXHAUSTED",
    "STATUS_LOW",
    "STATUS_OK",
    "QuotaExhausted",
    "can_spend",
    "ensure_can_spend",
    "mark_exhausted",
    "month_key",
    "monthly_limit",
    "note_local_spend",
    "note_provider_error",
    "record_headers",
    "reset_for_tests",
    "safety_margin",
    "snapshot",
]
