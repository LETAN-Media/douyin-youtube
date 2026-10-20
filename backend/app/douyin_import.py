"""Admin-driven Douyin inventory import / refresh engine.

Why this module exists
----------------------
Discovery is admin-driven: source creation starts one initial import and all
later scans are manual. Two operations live here:

* :func:`initial_import` — a one-off backlog walk for a source. It pages until
  ``has_more=false``, persists **each page immediately**, and stores the cursor
  after every page so a transient stop can resume later instead of refetching
  page 1.
* :func:`refresh_source` — the manual "check for new videos" action. It reads
  page 1 (newest first) and stops at the first ``aweme_id`` already in the
  inventory.

Both use ``fetch_page`` when the active provider supports it. RapidAPI is
quota-gated (see :mod:`app.douyin_quota`); self-hosted providers are not.
Nothing here schedules itself.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import douyin_quota
from app.config import settings
from app.db import SessionLocal
from app.douyin_inventory_providers import get_primary_provider
from app.inventory import _upsert_videos
from app.models import DouyinSource, DouyinVideo, Pipeline

logger = logging.getLogger("douyin-youtube-import")

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_PAUSED_QUOTA = "paused_quota"
STATUS_PAUSED = "paused"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

PROVIDER_OK = "ok"
PROVIDER_QUOTA = "quota_exhausted"
PROVIDER_ERROR = "provider_error"
PROVIDER_INVALID = "invalid"
PROVIDER_RISK_CONTROL = "risk_control"

#: Sources with an import/refresh in flight *in this process*, so two button
#: clicks cannot spend the same page twice.
_active_lock = threading.Lock()
_active_sources: set[str] = set()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _claim(source_id: str) -> bool:
    with _active_lock:
        if source_id in _active_sources:
            return False
        _active_sources.add(source_id)
        return True


def _release(source_id: str) -> None:
    with _active_lock:
        _active_sources.discard(source_id)


def _summary(
    source_id: str,
    status: str,
    *,
    new: int = 0,
    updated: int = 0,
    pages: int = 0,
    videos: int = 0,
    cursor: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "status": status,
        "new": new,
        "updated": updated,
        "pages": pages,
        "videos": videos,
        "cursor": cursor,
        "error": error,
        "quota": quota_status(),
    }


def _provider_uses_quota(provider: Any) -> bool:
    """True only for providers billed through the RapidAPI quota.

    Test doubles and legacy providers may omit the attribute, so the provider
    name is also checked; self_hosted/revid never consume RapidAPI quota.
    """
    explicit = getattr(provider, "uses_rapidapi_quota", None)
    if explicit is not None:
        return bool(explicit)
    return getattr(provider, "name", "") == "rapidapi_justone"


def quota_status() -> dict[str, Any]:
    """Public quota view for the API/UI. Contains no secrets."""
    snap = douyin_quota.snapshot()
    snap["safety_margin"] = douyin_quota.safety_margin()
    try:
        provider = get_primary_provider()
        snap["provider"] = getattr(provider, "name", None)
        snap["required"] = _provider_uses_quota(provider)
    except Exception:
        snap["provider"] = None
        snap["required"] = True
    return snap


def can_start_import() -> bool:
    """Provider-aware gate used by the API before queueing a scan."""
    try:
        provider = get_primary_provider()
    except Exception:
        return False
    if not _provider_uses_quota(provider):
        return True
    try:
        return bool(douyin_quota.can_spend(1))
    except Exception:
        return True


def _is_page_limit_error(exc: Exception) -> bool:
    """Deeper-page upstream risk control is resumable, not a failure."""
    return exc.__class__.__name__ == "DouyinFeedPageLimitError"


def _fetch_page(
    provider: Any,
    *,
    sec_uid: str,
    profile_url: str,
    source_id: str,
    cursor: str | None,
) -> dict[str, Any]:
    if hasattr(provider, "fetch_page"):
        return provider.fetch_page(sec_uid, cursor)
    # Compatibility fallback for providers that only expose fetch_all.
    items = provider.fetch_all(
        profile_url or f"https://www.douyin.com/user/{sec_uid}",
        sec_uid,
        source_id,
    )
    return {"items": list(items), "has_more": False, "next_cursor": ""}


def _resolve_sec_uid(source: DouyinSource) -> str:
    sec_uid = (source.douyin_sec_uid or source.douyin_user_id or "").strip()
    if sec_uid:
        return sec_uid
    profile_url = (source.profile_url or "").strip()
    if not profile_url:
        return ""
    try:
        from app.douyin_url import parse_douyin_profile_url

        parsed = parse_douyin_profile_url(profile_url)
        if parsed is not None:
            return parsed.sec_uid
    except Exception:
        pass
    return profile_url.rstrip("/").split("?")[0].rsplit("/", 1)[-1]


def _provider():
    return get_primary_provider()


def _recount(db: Session, source_id: str) -> int:
    total = db.execute(
        select(func.count(DouyinVideo.id)).where(DouyinVideo.source_id == source_id)
    ).scalar_one_or_none() or 0
    return int(total)


def _persist_page(
    *,
    source_id: str,
    items: list[dict[str, Any]],
    backfill: bool,
    cursor: str | None,
    count_videos: int | None = None,
    import_pages_delta: int = 0,
) -> tuple[int, int]:
    """Upsert one fetched page inside its own short transaction.

    Persisting per page (rather than at the end) means a crash or quota stop
    never loses already-paid-for videos.
    """
    if not items and not import_pages_delta and not cursor:
        return 0, 0
    with SessionLocal.begin() as db:
        source = db.get(DouyinSource, source_id)
        if source is None:
            return 0, 0
        pipeline = db.get(Pipeline, source.pipeline_id) if source.pipeline_id else None
        if pipeline is None:
            return 0, 0
        new_count, updated_count = _upsert_videos(
            db, source=source, pipeline=pipeline, videos=items, backfill=backfill
        )
        # Never clobber a stored resume cursor with an empty value; completion
        # clears it explicitly in _finish().
        if cursor:
            source.initial_import_cursor = cursor
        if import_pages_delta:
            source.initial_import_pages = int(source.initial_import_pages or 0) + import_pages_delta
        if count_videos:
            source.initial_import_videos = int(source.initial_import_videos or 0) + count_videos
        source.inventory_count = _recount(db, source_id)
        if items:
            first = str(items[0].get("video_id") or "").strip()
            if first:
                source.last_video_id = first
    return new_count, updated_count


def _finish(
    source_id: str,
    status: str,
    *,
    provider_status: str,
    detail: str | None,
    completed: bool = False,
) -> None:
    with SessionLocal.begin() as db:
        source = db.get(DouyinSource, source_id)
        if source is None:
            return
        source.initial_import_status = status
        source.inventory_sync_status = (
            "completed" if status == STATUS_COMPLETED else (
                "failed" if status == STATUS_FAILED else status
            )
        )
        source.inventory_sync_error = detail
        source.initial_import_last_error = detail
        source.provider_status = provider_status
        source.provider_status_detail = detail
        if completed:
            source.initial_import_cursor = None
            source.initial_import_completed_at = utcnow()
            source.inventory_synced_at = utcnow()
            source.last_checked_at = utcnow()
            source.last_scan_at = utcnow()


def initial_import(source_id: str, resume: bool = False) -> dict[str, Any]:
    """Walk a creator's backlog page by page until ``has_more=false``.

    Resumable: when the quota floor stops the walk the cursor is kept and the
    status becomes ``paused_quota``; calling again with ``resume=True``
    continues from that cursor instead of refetching page 1.
    """
    if not _claim(source_id):
        return _summary(source_id, "already_running")

    try:
        with SessionLocal() as db:
            source = db.get(DouyinSource, source_id)
            if source is None:
                return _summary(source_id, STATUS_FAILED, error="Không tìm thấy source")
            sec_uid = _resolve_sec_uid(source)
            if not sec_uid:
                _finish(
                    source_id, STATUS_FAILED,
                    provider_status=PROVIDER_INVALID,
                    detail="DOUYIN_SOURCE_INVALID: thiếu secUid/profile_url",
                )
                return _summary(
                    source_id, STATUS_FAILED,
                    error="DOUYIN_SOURCE_INVALID: thiếu secUid/profile_url",
                )
            profile_url = source.profile_url or ""
            cursor = (source.initial_import_cursor or None) if resume else None
            if not resume:
                source.initial_import_cursor = None
                source.initial_import_pages = 0
                source.initial_import_videos = 0
                source.initial_import_completed_at = None
            source.initial_import_status = STATUS_RUNNING
            source.initial_import_last_error = None
            source.initial_import_started_at = utcnow()
            source.inventory_sync_status = "running"
            source.inventory_sync_error = None
            provider_name = _provider().name
            source.feed_provider = provider_name
            db.commit()

        try:
            provider = _provider()
        except Exception as exc:
            _finish(
                source_id, STATUS_FAILED,
                provider_status=PROVIDER_ERROR, detail=str(exc)[:2000],
            )
            return _summary(source_id, STATUS_FAILED, error=str(exc)[:2000])

        max_pages = max(1, int(getattr(settings, "douyin_initial_import_max_pages", 50) or 50))
        delay = float(
            getattr(settings, "douyin_initial_import_page_delay_seconds", 0.5) or 0
        )
        uses_quota = _provider_uses_quota(provider)

        new_total = 0
        updated_total = 0
        pages = 0
        seen: set[str] = set()
        status = STATUS_COMPLETED
        error: str | None = None
        provider_status = PROVIDER_OK

        while pages < max_pages:
            if uses_quota and not douyin_quota.can_spend(1):
                status = STATUS_PAUSED_QUOTA
                provider_status = PROVIDER_QUOTA
                error = (
                    f"RAPIDAPI_QUOTA_EXHAUSTED: còn {douyin_quota.snapshot()['remaining']} "
                    "request — dừng import, giữ cursor để chạy tiếp."
                )
                break

            try:
                page = _fetch_page(
                    provider,
                    sec_uid=sec_uid,
                    profile_url=profile_url,
                    source_id=source_id,
                    cursor=cursor,
                )
            except douyin_quota.QuotaExhausted as exc:  # defensive
                status = STATUS_PAUSED_QUOTA
                provider_status = PROVIDER_QUOTA
                error = str(exc)[:2000]
                break
            except Exception as exc:
                text = str(exc)
                if _is_page_limit_error(exc):
                    status = STATUS_PAUSED
                    provider_status = PROVIDER_RISK_CONTROL
                elif uses_quota and (
                    "QUOTA" in text.upper()
                    or isinstance(exc, douyin_quota.QuotaExhausted)
                ):
                    status = STATUS_PAUSED_QUOTA
                    provider_status = PROVIDER_QUOTA
                else:
                    status = STATUS_FAILED
                    provider_status = PROVIDER_ERROR
                error = text[:2000]
                break

            items = list(page.get("items") or [])
            fresh = [it for it in items if str(it.get("video_id") or "") not in seen]
            seen.update(str(it.get("video_id") or "") for it in items)
            new_count, updated_count = _persist_page(
                source_id=source_id,
                items=items,
                backfill=True,
                cursor=cursor,
                count_videos=len([it for it in fresh if it.get("video_id")]),
                import_pages_delta=1,
            )
            new_total += new_count
            updated_total += updated_count
            pages += 1
            logger.info(
                "Initial import page %s for source=%s: %s items, %s new, %s updated",
                pages, source_id, len(items), new_count, updated_count,
            )

            if not page.get("has_more"):
                break
            next_cursor = str(page.get("next_cursor") or "")
            if not next_cursor or next_cursor == "0":
                break
            cursor = next_cursor
            # Persist the resume point as soon as it is known.
            _persist_page(
                source_id=source_id, items=[], backfill=True, cursor=cursor,
            )
            if delay > 0:
                time.sleep(delay)
        else:
            # Hit the configured page ceiling with more pages available.
            status = STATUS_PAUSED
            provider_status = PROVIDER_OK
            error = (
                f"Đã chạy {max_pages} trang (giới hạn cấu hình) — còn dữ liệu, "
                "chạy lại để tiếp tục."
            )

        if status == STATUS_COMPLETED:
            _finish(
                source_id, STATUS_COMPLETED,
                provider_status=PROVIDER_OK, detail=None, completed=True,
            )
        else:
            _finish(
                source_id, status,
                provider_status=provider_status, detail=error,
            )

        return _summary(
            source_id, status,
            new=new_total, updated=updated_total, pages=pages,
            videos=len(seen), cursor=cursor, error=error,
        )
    finally:
        _release(source_id)


def refresh_source(source_id: str) -> dict[str, Any]:
    """Manual "new videos" refresh: page 1 newest-first, stop at the first
    ``aweme_id`` already in the inventory."""
    if not _claim(source_id):
        return _summary(source_id, "already_running")

    try:
        with SessionLocal() as db:
            source = db.get(DouyinSource, source_id)
            if source is None:
                return _summary(source_id, STATUS_FAILED, error="Không tìm thấy source")
            sec_uid = _resolve_sec_uid(source)
            if not sec_uid:
                return _summary(
                    source_id, STATUS_FAILED,
                    error="DOUYIN_SOURCE_INVALID: thiếu secUid/profile_url",
                )
            profile_url = source.profile_url or ""
            known_ids = set(
                str(v) for v in db.execute(
                    select(DouyinVideo.video_id).where(
                        DouyinVideo.source_id == source_id
                    )
                ).scalars().all()
            )
            source.inventory_sync_status = "running"
            source.inventory_sync_error = None

        try:
            provider = _provider()
        except Exception as exc:
            _finish(
                source_id, STATUS_FAILED,
                provider_status=PROVIDER_ERROR, detail=str(exc)[:2000],
            )
            return _summary(source_id, STATUS_FAILED, error=str(exc)[:2000])

        max_pages = max(
            1, int(getattr(settings, "douyin_refresh_max_pages", 3) or 3)
        )
        uses_quota = _provider_uses_quota(provider)
        cursor: str | None = None
        pages = 0
        new_total = 0
        updated_total = 0
        seen: set[str] = set()
        status = STATUS_COMPLETED
        error: str | None = None
        provider_status = PROVIDER_OK

        while pages < max_pages:
            if uses_quota and not douyin_quota.can_spend(1):
                status = STATUS_PAUSED_QUOTA
                provider_status = PROVIDER_QUOTA
                error = (
                    "RAPIDAPI_QUOTA_EXHAUSTED: hết quota — không gọi thêm request nào."
                )
                break
            try:
                page = _fetch_page(
                    provider,
                    sec_uid=sec_uid,
                    profile_url=profile_url,
                    source_id=source_id,
                    cursor=cursor,
                )
            except Exception as exc:
                text = str(exc)
                if _is_page_limit_error(exc):
                    status = STATUS_PAUSED
                    provider_status = PROVIDER_RISK_CONTROL
                elif uses_quota and "QUOTA" in text.upper():
                    status = STATUS_PAUSED_QUOTA
                    provider_status = PROVIDER_QUOTA
                else:
                    status = STATUS_FAILED
                    provider_status = PROVIDER_ERROR
                error = text[:2000]
                break

            items = list(page.get("items") or [])
            pages += 1
            if not items:
                break

            batch: list[dict[str, Any]] = []
            hit_known = False
            for item in items:
                vid = str(item.get("video_id") or "").strip()
                if not vid or vid in seen:
                    continue
                if vid in known_ids:
                    hit_known = True
                    break
                seen.add(vid)
                batch.append(item)

            if batch:
                new_count, updated_count = _persist_page(
                    source_id=source_id,
                    items=batch,
                    backfill=False,
                    cursor=None,
                )
                new_total += new_count
                updated_total += updated_count

            if hit_known or not page.get("has_more"):
                break
            next_cursor = str(page.get("next_cursor") or "")
            if not next_cursor or next_cursor == "0":
                break
            cursor = next_cursor

        with SessionLocal.begin() as db:
            source = db.get(DouyinSource, source_id)
            if source is not None:
                source.last_refresh_at = utcnow()
                source.provider_status = provider_status
                source.provider_status_detail = error
                if status == STATUS_COMPLETED:
                    source.inventory_sync_status = "completed"
                    source.inventory_sync_error = None
                    source.inventory_synced_at = utcnow()
                    source.last_checked_at = utcnow()
                    source.last_scan_at = utcnow()
                elif status in (STATUS_PAUSED_QUOTA, STATUS_PAUSED):
                    source.inventory_sync_status = status
                    source.inventory_sync_error = error
                else:
                    source.inventory_sync_status = "failed"
                    source.inventory_sync_error = error

        logger.info(
            "Refresh source=%s: %s page(s), %s new, %s updated, status=%s",
            source_id, pages, new_total, updated_total, status,
        )
        return _summary(
            source_id, status,
            new=new_total, updated=updated_total, pages=pages,
            videos=len(seen), error=error,
        )
    finally:
        _release(source_id)


def list_source_inventory(
    source_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Inventory rows for one source, newest first."""
    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, int(offset or 0))
    with SessionLocal() as db:
        rows = list(
            db.execute(
                select(DouyinVideo)
                .where(DouyinVideo.source_id == source_id)
                .order_by(
                    DouyinVideo.douyin_created_at.desc().nullslast(),
                    DouyinVideo.created_at.desc(),
                )
                .offset(offset)
                .limit(limit)
            ).scalars().all()
        )
        total = _recount(db, source_id)
    return {
        "source_id": source_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "videos": [
            {
                "id": v.id,
                "video_id": v.video_id,
                "title": v.title,
                "url": v.url,
                "thumbnail_url": v.thumbnail_url,
                "duration": v.duration,
                "status": v.status,
                "is_backlog": bool(v.is_backlog),
                "is_backfill": bool(v.is_backfill),
                "douyin_created_at": v.douyin_created_at,
            }
            for v in rows
        ],
    }


__all__ = [
    "PROVIDER_ERROR",
    "PROVIDER_INVALID",
    "PROVIDER_OK",
    "PROVIDER_QUOTA",
    "PROVIDER_RISK_CONTROL",
    "STATUS_COMPLETED",
    "STATUS_FAILED",
    "STATUS_PAUSED",
    "STATUS_PAUSED_QUOTA",
    "STATUS_PENDING",
    "STATUS_RUNNING",
    "can_start_import",
    "initial_import",
    "list_source_inventory",
    "quota_status",
    "refresh_source",
]
