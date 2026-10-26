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

import json
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
from app.douyin_inventory_providers import (
    get_default_provider_id,
    get_primary_provider,
)
from app.integrations.rapidapi.errors import RapidApiPoolError
from app.inventory import _upsert_videos
from app.models import DouyinScanJob, DouyinSource, DouyinVideo, Pipeline

logger = logging.getLogger("douyin-youtube-import")

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_PAUSED_QUOTA = "paused_quota"
STATUS_PAUSED = "paused"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_PARTIAL = "partial"

STOP_REASON_END_OF_RESULTS = "END_OF_RESULTS"
STOP_REASON_QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
STOP_REASON_MAX_PAGES_REACHED = "MAX_PAGES_REACHED"
STOP_REASON_KNOWN_REELS_REACHED = "KNOWN_REELS_REACHED"
STOP_REASON_SAFETY_LIMIT = "SAFETY_LIMIT"
STOP_REASON_ERROR = "ERROR"

PROVIDER_OK = "ok"
PROVIDER_QUOTA = "quota_exhausted"
PROVIDER_ERROR = "provider_error"
PROVIDER_INVALID = "invalid"

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
    provider: str | None = None,
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
        "provider": provider,
        "quota": quota_status(),
    }


def _provider_uses_quota(provider: Any) -> bool:
    """True only for providers billed through the RapidAPI quota.

    Test doubles and legacy providers may omit the attribute, so the provider
    name is also checked; only rapidapi_justone consumes RapidAPI quota.
    """
    explicit = getattr(provider, "uses_rapidapi_quota", None)
    if explicit is not None:
        return bool(explicit)
    return getattr(provider, "name", "") == "rapidapi_justone"


def quota_status() -> dict[str, Any]:
    """Public quota view for the API/UI. Contains no secrets."""
    try:
        provider = get_primary_provider()
    except Exception:
        provider = None
    if provider is not None and hasattr(provider, "quota_status"):
        try:
            snap = provider.quota_status()
            snap.setdefault("safety_margin", douyin_quota.safety_margin())
            snap.setdefault("required", True)
            return snap
        except Exception:
            pass
    snap = douyin_quota.snapshot()
    snap["safety_margin"] = douyin_quota.safety_margin()
    snap["provider"] = getattr(provider, "name", None) if provider else None
    snap["required"] = _provider_uses_quota(provider) if provider else True
    return snap


def can_start_import() -> bool:
    """Provider-aware gate used by the API before queueing a scan."""
    try:
        provider = get_primary_provider()
    except Exception:
        return False
    if hasattr(provider, "has_available_provider"):
        try:
            return bool(provider.has_available_provider())
        except Exception:
            return False
    if not _provider_uses_quota(provider):
        return True
    try:
        return bool(douyin_quota.can_spend(1))
    except Exception:
        return True


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
    if sec_uid and sec_uid.startswith("MS4wLjABAAAA"):
        return sec_uid
    profile_url = (source.profile_url or source.original_profile_url or "").strip()
    if not profile_url:
        return sec_uid
    try:
        from app.douyin_url import parse_douyin_profile_url

        parsed = parse_douyin_profile_url(profile_url)
        if parsed is not None and parsed.sec_uid:
            try:
                with SessionLocal.begin() as db:
                    s_db = db.get(DouyinSource, source.id)
                    if s_db and not s_db.douyin_sec_uid:
                        s_db.douyin_sec_uid = parsed.sec_uid
                        s_db.profile_url = parsed.canonical
            except Exception:
                pass
            return parsed.sec_uid
    except Exception:
        pass
    if profile_url.startswith("http://") or profile_url.startswith("https://"):
        return profile_url
    return profile_url.rstrip("/").split("?")[0].rsplit("/", 1)[-1]


def _provider():
    return get_primary_provider()


class _PageSource:
    """Adapter over either a pool scan session or a legacy provider."""

    def __init__(
        self,
        provider: Any,
        *,
        sec_uid: str,
        profile_url: str,
        source_id: str,
        preferred_provider_id: str | None = None,
    ) -> None:
        self.provider = provider
        self.sec_uid = sec_uid
        self.profile_url = profile_url
        self.source_id = source_id
        self.pool_managed = hasattr(provider, "open_scan")
        self.session = (
            provider.open_scan(
                sec_uid,
                preferred_provider_id=preferred_provider_id,
            )
            if self.pool_managed
            else None
        )
        self.provider_id = (
            preferred_provider_id
            or getattr(provider, "name", None)
            or "rapidapi_justone"
        )

    def fetch_page(self, cursor: str | None) -> dict[str, Any]:
        if self.session is not None:
            page = self.session.fetch_page(cursor)
            if getattr(self.session, "provider_id", None):
                self.provider_id = str(self.session.provider_id)
            return page
        return _fetch_page(
            self.provider,
            sec_uid=self.sec_uid,
            profile_url=self.profile_url,
            source_id=self.source_id,
            cursor=cursor,
        )


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
    provider_id: str | None = None,
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
        if provider_id:
            source.feed_provider = provider_id
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
    provider_id: str | None = None,
    scan_stats: dict[str, Any] | None = None,
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
        if provider_id:
            source.feed_provider = provider_id
        if scan_stats is not None:
            source.last_scan_stats = json.dumps(scan_stats, ensure_ascii=False)
        if completed:
            source.initial_import_cursor = None
            source.initial_import_completed_at = utcnow()
            source.inventory_synced_at = utcnow()
            source.last_checked_at = utcnow()
            source.last_scan_at = utcnow()


def queue_scan_job(
    db: Session,
    source_id: str,
    scan_mode: str = "initial",
    resume: bool = False,
) -> DouyinScanJob:
    """Queue a durable scan job for a source with deduplication check."""
    existing = db.execute(
        select(DouyinScanJob)
        .where(DouyinScanJob.source_id == source_id)
        .where(DouyinScanJob.status.in_([STATUS_PENDING, STATUS_RUNNING]))
        .order_by(DouyinScanJob.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    source = db.get(DouyinSource, source_id)
    if source is None:
        raise ValueError(f"DouyinSource {source_id} not found")

    cursor = source.initial_import_cursor if resume else None
    mode = "resume" if resume else scan_mode
    job = DouyinScanJob(
        workspace_id=source.workspace_id,
        pipeline_id=source.pipeline_id,
        source_id=source.id,
        scan_mode=mode,
        status=STATUS_PENDING,
        cursor=cursor,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def recover_incomplete_scan_jobs(db: Session | None = None) -> int:
    """Recover scan jobs left in 'running' state after container restart or crash."""
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    try:
        stuck_jobs = db.execute(
            select(DouyinScanJob).where(DouyinScanJob.status == STATUS_RUNNING)
        ).scalars().all()
        recovered = 0
        for job in stuck_jobs:
            job.retry_count = int(job.retry_count or 0) + 1
            if job.retry_count > 5:
                job.status = STATUS_FAILED
                job.stop_reason = STOP_REASON_ERROR
                job.error = "Max retries exceeded after crash recovery"
            else:
                job.status = STATUS_PENDING
            job.locked_at = None
            job.locked_by = None
            recovered += 1
        if recovered:
            db.commit()
            logger.info("Recovered %s stuck DouyinScanJob(s)", recovered)
        return recovered
    finally:
        if should_close:
            db.close()


def claim_and_run_scan_job(
    job_id: str | None = None,
    worker_id: str = "main",
) -> dict[str, Any] | None:
    """Claim a pending scan job and execute it."""
    claimed_id: str | None = None
    with SessionLocal.begin() as db:
        if job_id is not None:
            job = db.get(DouyinScanJob, job_id)
            if job is None or job.status not in (STATUS_PENDING, STATUS_PAUSED_QUOTA):
                return None
        else:
            job = db.execute(
                select(DouyinScanJob)
                .where(DouyinScanJob.status == STATUS_PENDING)
                .order_by(DouyinScanJob.created_at.asc())
                .limit(1)
            ).scalar_one_or_none()
            if job is None:
                return None

        job.status = STATUS_RUNNING
        job.locked_at = utcnow()
        job.locked_by = worker_id
        job.started_at = utcnow()
        claimed_id = job.id

    if not claimed_id:
        return None

    return execute_scan_job(claimed_id, worker_id=worker_id)


def _execute_self_hosted_fallback(
    *,
    job_id: str | None,
    source_id: str,
    pipeline_id: str,
    profile_url: str,
    original_profile_url: str | None,
    sec_uid: str,
    scan_mode: str,
    is_backlog: bool,
    existing_error: str | None = None,
) -> dict[str, Any] | None:
    """Fallback scanner using self-hosted Douyin API when RapidAPI pool fails."""
    if not getattr(settings, "douyin_self_hosted_enabled", True):
        return None

    target_url = (
        (original_profile_url or "").strip()
        or (profile_url or "").strip()
        or (f"https://www.douyin.com/user/{sec_uid}" if sec_uid else "")
    )
    if not target_url:
        return None

    logger.info(
        "RapidAPI failed (%s); attempting Douyin self-hosted fallback for source=%s url=%s",
        (existing_error or "")[:120],
        source_id,
        target_url,
    )

    try:
        from app.douyin_self_hosted import DouyinSelfHostedClient
        client = DouyinSelfHostedClient()
        items = client.fetch_video_items(
            target_url,
            max_count=int(getattr(settings, "douyin_self_hosted_max_count", 200) or 200),
        )
    except Exception as exc:
        logger.warning(
            "Douyin self-hosted fallback failed for source=%s: %s",
            source_id,
            exc,
        )
        return None

    new_count, updated_count = _persist_page(
        source_id=source_id,
        items=items,
        backfill=is_backlog,
        cursor=None,
        provider_id="douyin_self_hosted",
    )

    status = STATUS_COMPLETED
    stop_reason = STOP_REASON_END_OF_RESULTS
    duplicate_count = max(0, len(items) - new_count)

    scan_stats = {
        "job_id": job_id,
        "scan_mode": scan_mode,
        "provider": "douyin_self_hosted",
        "pages": 1,
        "found": len(items),
        "new": new_count,
        "duplicates": duplicate_count,
        "status": status,
        "stop_reason": stop_reason,
    }

    if job_id:
        with SessionLocal.begin() as db:
            j = db.get(DouyinScanJob, job_id)
            if j:
                j.status = status
                j.stop_reason = stop_reason
                j.provider_id = "douyin_self_hosted"
                j.pages_scanned = 1
                j.videos_discovered = len(items)
                j.videos_new = new_count
                j.videos_duplicate = duplicate_count
                j.error = None
                j.completed_at = utcnow()
                j.locked_at = None
                j.locked_by = None

    if is_backlog:
        _finish(
            source_id,
            status,
            provider_status=PROVIDER_OK,
            detail=f"Discovered {len(items)} videos ({new_count} new) via self-hosted fallback",
            completed=True,
            provider_id="douyin_self_hosted",
            scan_stats=scan_stats,
        )
    else:
        with SessionLocal.begin() as db:
            source = db.get(DouyinSource, source_id)
            if source is not None:
                source.last_refresh_at = utcnow()
                source.last_scan_at = utcnow()
                source.provider_status = PROVIDER_OK
                source.provider_status_detail = f"Discovered {len(items)} videos ({new_count} new) via self-hosted fallback"
                source.feed_provider = "douyin_self_hosted"
                source.last_scan_stats = json.dumps(scan_stats, ensure_ascii=False)
                source.inventory_sync_status = "completed"
                source.inventory_sync_error = None
                source.inventory_synced_at = utcnow()
                source.last_checked_at = utcnow()

    logger.info(
        "Self-hosted fallback completed for source=%s: found=%d new=%d duplicates=%d",
        source_id,
        len(items),
        new_count,
        duplicate_count,
    )

    return _summary(
        source_id,
        status,
        new=new_count,
        updated=updated_count,
        pages=1,
        videos=len(items),
        provider="douyin_self_hosted",
    )


def scan_source_self_hosted(source_id: str, max_count: int | None = None) -> dict[str, Any]:
    """Explicitly scan a Douyin source using the self-hosted API."""
    with SessionLocal() as db:
        source = db.get(DouyinSource, source_id)
        if source is None:
            return _summary(source_id, STATUS_FAILED, error="Source not found")
        pipeline_id = source.pipeline_id
        profile_url = source.profile_url or ""
        original_profile_url = source.original_profile_url
        sec_uid = source.douyin_sec_uid or ""

    if not _claim(source_id):
        return _summary(source_id, "already_running")

    try:
        job = None
        with SessionLocal() as db:
            job = queue_scan_job(db, source_id, scan_mode="manual_refresh")
        job_id = job.id if job else None

        res = _execute_self_hosted_fallback(
            job_id=job_id,
            source_id=source_id,
            pipeline_id=pipeline_id,
            profile_url=profile_url,
            original_profile_url=original_profile_url,
            sec_uid=sec_uid,
            scan_mode="manual_refresh",
            is_backlog=False,
        )
        if res is not None:
            return res
        return _summary(source_id, STATUS_FAILED, error="Self-hosted scan failed to execute")
    finally:
        _release(source_id)


def execute_scan_job(job_id: str, worker_id: str = "main") -> dict[str, Any]:
    """Execute a claimed DouyinScanJob, handling initial or incremental scan."""
    with SessionLocal() as db:
        job = db.get(DouyinScanJob, job_id)
        if job is None:
            return _summary("unknown", STATUS_FAILED, error=f"ScanJob {job_id} not found")
        source_id = job.source_id
        scan_mode = job.scan_mode
        initial_cursor = job.cursor

    if not _claim(source_id):
        # Reset db state so it can run later
        with SessionLocal.begin() as db:
            j = db.get(DouyinScanJob, job_id)
            if j and j.status == STATUS_RUNNING:
                j.status = STATUS_PENDING
                j.locked_at = None
                j.locked_by = None
        return _summary(source_id, "already_running")

    try:
        with SessionLocal() as db:
            source = db.get(DouyinSource, source_id)
            if source is None:
                with SessionLocal.begin() as s_db:
                    j = s_db.get(DouyinScanJob, job_id)
                    if j:
                        j.status = STATUS_FAILED
                        j.stop_reason = STOP_REASON_ERROR
                        j.error = "Không tìm thấy source"
                        j.completed_at = utcnow()
                        j.locked_at = None
                        j.locked_by = None
                return _summary(source_id, STATUS_FAILED, error="Không tìm thấy source")

            sec_uid = _resolve_sec_uid(source)
            if not sec_uid:
                err_msg = "DOUYIN_SOURCE_INVALID: thiếu secUid/profile_url"
                with SessionLocal.begin() as s_db:
                    j = s_db.get(DouyinScanJob, job_id)
                    if j:
                        j.status = STATUS_FAILED
                        j.stop_reason = STOP_REASON_ERROR
                        j.error = err_msg
                        j.completed_at = utcnow()
                        j.locked_at = None
                        j.locked_by = None
                _finish(
                    source_id, STATUS_FAILED,
                    provider_status=PROVIDER_INVALID,
                    detail=err_msg,
                )
                return _summary(source_id, STATUS_FAILED, error=err_msg)

            profile_url = source.profile_url or ""
            original_profile_url = source.original_profile_url
            pipeline_id = source.pipeline_id
            stored_cursor = source.initial_import_cursor
            preferred_provider_id = (
                (source.feed_provider or None) if scan_mode == "resume" else None
            )
            is_backlog = scan_mode in ("initial", "resume", "full")
            if is_backlog:
                if scan_mode != "resume":
                    source.initial_import_cursor = None
                    source.initial_import_pages = 0
                    source.initial_import_videos = 0
                    source.initial_import_completed_at = None
                    source.feed_provider = get_default_provider_id()
                source.initial_import_status = STATUS_RUNNING
                source.initial_import_last_error = None
                source.initial_import_started_at = utcnow()

            source.inventory_sync_status = "running"
            source.inventory_sync_error = None
            db.commit()

        try:
            provider = _provider()
            page_source = _PageSource(
                provider,
                sec_uid=sec_uid,
                profile_url=profile_url,
                source_id=source_id,
                preferred_provider_id=preferred_provider_id,
            )
        except RapidApiPoolError as exc:
            fallback_res = _execute_self_hosted_fallback(
                job_id=job_id,
                source_id=source_id,
                pipeline_id=pipeline_id,
                profile_url=profile_url,
                original_profile_url=original_profile_url,
                sec_uid=sec_uid,
                scan_mode=scan_mode,
                is_backlog=is_backlog,
                existing_error=exc.summary(),
            )
            if fallback_res is not None:
                return fallback_res
            error = exc.summary()
            status = STATUS_PAUSED_QUOTA if exc.quota_exhausted else STATUS_FAILED
            provider_status = PROVIDER_QUOTA if exc.quota_exhausted else PROVIDER_ERROR
            stop_reason = STOP_REASON_QUOTA_EXHAUSTED if exc.quota_exhausted else STOP_REASON_ERROR
            with SessionLocal.begin() as db:
                j = db.get(DouyinScanJob, job_id)
                if j:
                    j.status = status
                    j.stop_reason = stop_reason
                    j.error = error
                    j.completed_at = utcnow()
                    j.locked_at = None
                    j.locked_by = None
            scan_stats = {
                "job_id": job_id,
                "scan_mode": scan_mode,
                "provider": preferred_provider_id,
                "pages": 0,
                "found": 0,
                "new": 0,
                "duplicates": 0,
                "status": status,
                "stop_reason": stop_reason,
            }
            _finish(
                source_id,
                status,
                provider_status=provider_status,
                detail=error,
                scan_stats=scan_stats,
            )
            return _summary(
                source_id, status, error=error, provider=preferred_provider_id
            )
        except Exception as exc:
            err_text = str(exc)[:2000]
            with SessionLocal.begin() as db:
                j = db.get(DouyinScanJob, job_id)
                if j:
                    j.status = STATUS_FAILED
                    j.stop_reason = STOP_REASON_ERROR
                    j.error = err_text
                    j.completed_at = utcnow()
                    j.locked_at = None
                    j.locked_by = None
            _finish(
                source_id, STATUS_FAILED,
                provider_status=PROVIDER_ERROR, detail=err_text,
            )
            return _summary(source_id, STATUS_FAILED, error=err_text)

        uses_quota = _provider_uses_quota(provider)
        delay = float(
            getattr(settings, "douyin_initial_import_page_delay_seconds", 0.5) or 0
        )
        if is_backlog:
            max_pages = max(1, int(getattr(settings, "douyin_initial_import_max_pages", 50) or 50))
            cursor = initial_cursor or ((stored_cursor or None) if scan_mode == "resume" else None)
        else:
            max_pages = max(1, int(getattr(settings, "douyin_refresh_max_pages", 3) or 3))
            known_pages_stop = max(1, int(getattr(settings, "douyin_known_pages_stop", 1) or 1))
            cursor = None
            with SessionLocal() as db:
                known_ids = set(
                    str(v) for v in db.execute(
                        select(DouyinVideo.video_id).where(
                            (DouyinVideo.source_id == source_id) |
                            ((DouyinVideo.pipeline_id == pipeline_id) & (DouyinVideo.source_id.is_(None)))
                        )
                    ).scalars().all()
                    if v
                )
            consecutive_known_pages = 0

        new_total = 0
        updated_total = 0
        found_total = 0
        pages = 0
        seen: set[str] = set()
        status = STATUS_COMPLETED
        stop_reason = STOP_REASON_END_OF_RESULTS
        error: str | None = None
        provider_status = PROVIDER_OK

        while pages < max_pages:
            if not page_source.pool_managed and uses_quota and not douyin_quota.can_spend(1):
                status = STATUS_PAUSED_QUOTA
                stop_reason = STOP_REASON_QUOTA_EXHAUSTED
                provider_status = PROVIDER_QUOTA
                error = (
                    f"RAPIDAPI_QUOTA_EXHAUSTED: còn {douyin_quota.snapshot()['remaining']} "
                    "request — dừng scan, giữ cursor để chạy tiếp."
                )
                break

            try:
                page = page_source.fetch_page(cursor)
            except RapidApiPoolError as exc:
                if pages == 0:
                    fallback_res = _execute_self_hosted_fallback(
                        job_id=job_id,
                        source_id=source_id,
                        pipeline_id=pipeline_id,
                        profile_url=profile_url,
                        original_profile_url=original_profile_url,
                        sec_uid=sec_uid,
                        scan_mode=scan_mode,
                        is_backlog=is_backlog,
                        existing_error=exc.summary(),
                    )
                    if fallback_res is not None:
                        return fallback_res
                status = (
                    STATUS_PAUSED_QUOTA
                    if exc.quota_exhausted
                    else STATUS_FAILED
                )
                stop_reason = (
                    STOP_REASON_QUOTA_EXHAUSTED
                    if exc.quota_exhausted
                    else STOP_REASON_ERROR
                )
                provider_status = (
                    PROVIDER_QUOTA if exc.quota_exhausted else PROVIDER_ERROR
                )
                error = exc.summary()[:2000]
                break
            except douyin_quota.QuotaExhausted as exc:
                if pages == 0:
                    fallback_res = _execute_self_hosted_fallback(
                        job_id=job_id,
                        source_id=source_id,
                        pipeline_id=pipeline_id,
                        profile_url=profile_url,
                        original_profile_url=original_profile_url,
                        sec_uid=sec_uid,
                        scan_mode=scan_mode,
                        is_backlog=is_backlog,
                        existing_error=str(exc),
                    )
                    if fallback_res is not None:
                        return fallback_res
                status = STATUS_PAUSED_QUOTA
                stop_reason = STOP_REASON_QUOTA_EXHAUSTED
                provider_status = PROVIDER_QUOTA
                error = str(exc)[:2000]
                break
            except Exception as exc:
                text = str(exc)
                if uses_quota and (
                    "QUOTA" in text.upper()
                    or isinstance(exc, douyin_quota.QuotaExhausted)
                ):
                    status = STATUS_PAUSED_QUOTA
                    stop_reason = STOP_REASON_QUOTA_EXHAUSTED
                    provider_status = PROVIDER_QUOTA
                else:
                    status = STATUS_FAILED
                    stop_reason = STOP_REASON_ERROR
                    provider_status = PROVIDER_ERROR
                error = text[:2000]
                break

            items = list(page.get("items") or [])
            found_total += len(items)
            pages += 1

            if not is_backlog:
                # Incremental / Replenish mode: Safe stop with pinned-post resistance
                item_vids = [
                    str(it.get("video_id") or "").strip()
                    for it in items
                    if str(it.get("video_id") or "").strip()
                ]
                hit_known = any(vid in known_ids for vid in item_vids)
                all_known = bool(item_vids) and all(vid in known_ids for vid in item_vids)
                if all_known:
                    consecutive_known_pages += 1
                else:
                    consecutive_known_pages = 0

                new_count, updated_count = _persist_page(
                    source_id=source_id,
                    items=items,
                    backfill=False,
                    cursor=None,
                    provider_id=page_source.provider_id,
                )
                new_total += new_count
                updated_total += updated_count
                known_ids.update(item_vids)

                # Manual refresh stops at first known video boundary
                if scan_mode == "manual_refresh" and hit_known:
                    status = STATUS_COMPLETED
                    stop_reason = STOP_REASON_KNOWN_REELS_REACHED
                    break

                # Auto-replenishment uses consecutive known pages streak (pinned-post resistant)
                if consecutive_known_pages >= known_pages_stop:
                    status = STATUS_COMPLETED
                    stop_reason = STOP_REASON_KNOWN_REELS_REACHED
                    break
            else:
                # Backlog / Initial walk
                fresh = [it for it in items if str(it.get("video_id") or "") not in seen]
                seen.update(str(it.get("video_id") or "") for it in items)
                new_count, updated_count = _persist_page(
                    source_id=source_id,
                    items=items,
                    backfill=True,
                    cursor=cursor,
                    count_videos=len([it for it in fresh if it.get("video_id")]),
                    import_pages_delta=1,
                    provider_id=page_source.provider_id,
                )
                new_total += new_count
                updated_total += updated_count

            # Persist scan job progress to DB
            with SessionLocal.begin() as db:
                j = db.get(DouyinScanJob, job_id)
                if j:
                    j.pages_scanned = pages
                    j.videos_discovered = found_total
                    j.videos_new = new_total
                    j.videos_duplicate = max(0, found_total - new_total)
                    j.provider_id = page_source.provider_id

            if not page.get("has_more"):
                status = STATUS_COMPLETED
                stop_reason = STOP_REASON_END_OF_RESULTS
                break
            next_cursor = str(page.get("next_cursor") or "")
            if not next_cursor or next_cursor == "0":
                status = STATUS_COMPLETED
                stop_reason = STOP_REASON_END_OF_RESULTS
                break
            cursor = next_cursor
            if is_backlog:
                _persist_page(
                    source_id=source_id, items=[], backfill=True, cursor=cursor,
                )
            if delay > 0:
                time.sleep(delay)
        else:
            # Hit max_pages ceiling
            if is_backlog:
                status = STATUS_PAUSED
                stop_reason = STOP_REASON_MAX_PAGES_REACHED
                provider_status = PROVIDER_OK
                error = (
                    f"Đã chạy {max_pages} trang (giới hạn cấu hình) — còn dữ liệu, "
                    "chạy lại để tiếp tục."
                )
            else:
                status = STATUS_COMPLETED
                stop_reason = STOP_REASON_MAX_PAGES_REACHED
                provider_status = PROVIDER_OK

        # Persist final DouyinScanJob state
        with SessionLocal.begin() as db:
            j = db.get(DouyinScanJob, job_id)
            if j:
                j.status = status
                j.stop_reason = stop_reason
                j.error = error
                j.completed_at = utcnow()
                j.locked_at = None
                j.locked_by = None
                j.pages_scanned = pages
                j.videos_discovered = found_total
                j.videos_new = new_total
                j.videos_duplicate = max(0, found_total - new_total)
                j.cursor = cursor if status != STATUS_COMPLETED else None
                j.provider_id = page_source.provider_id

        scan_stats = {
            "job_id": job_id,
            "scan_mode": scan_mode,
            "provider": page_source.provider_id,
            "pages": pages,
            "found": found_total,
            "new": new_total,
            "duplicates": max(0, found_total - new_total),
            "status": status,
            "stop_reason": stop_reason,
        }

        completed = (status == STATUS_COMPLETED)
        if is_backlog:
            _finish(
                source_id,
                status,
                provider_status=provider_status,
                detail=error,
                completed=completed,
                provider_id=page_source.provider_id,
                scan_stats=scan_stats,
            )
        else:
            with SessionLocal.begin() as db:
                source = db.get(DouyinSource, source_id)
                if source is not None:
                    source.last_refresh_at = utcnow()
                    source.last_scan_at = utcnow()
                    source.provider_status = provider_status
                    source.provider_status_detail = error
                    source.feed_provider = page_source.provider_id
                    source.last_scan_stats = json.dumps(scan_stats, ensure_ascii=False)
                    if status == STATUS_COMPLETED:
                        source.inventory_sync_status = "completed"
                        source.inventory_sync_error = None
                        source.inventory_synced_at = utcnow()
                        source.last_checked_at = utcnow()
                    elif status in (STATUS_PAUSED_QUOTA, STATUS_PAUSED):
                        source.inventory_sync_status = status
                        source.inventory_sync_error = error
                    else:
                        source.inventory_sync_status = "failed"
                        source.inventory_sync_error = error

        return _summary(
            source_id,
            status,
            new=new_total,
            updated=updated_total,
            pages=pages,
            videos=len(seen) if is_backlog else found_total,
            cursor=cursor if status != STATUS_COMPLETED else None,
            error=error,
            provider=page_source.provider_id,
        )
    finally:
        _release(source_id)


def initial_import(source_id: str, resume: bool = False) -> dict[str, Any]:
    """Walk a creator's backlog page by page until has_more=false.
    Backed by a persistent DouyinScanJob."""
    with SessionLocal() as db:
        job = queue_scan_job(
            db, source_id, scan_mode="resume" if resume else "initial", resume=resume
        )
        job_id = job.id
    res = claim_and_run_scan_job(job_id=job_id, worker_id="initial_import_direct")
    return res if res is not None else _summary(source_id, "already_running")


def refresh_source(source_id: str) -> dict[str, Any]:
    """Manual "new videos" refresh: newest-first, with safe stop.
    Backed by a persistent DouyinScanJob."""
    with SessionLocal() as db:
        job = queue_scan_job(db, source_id, scan_mode="manual_refresh", resume=False)
        job_id = job.id
    res = claim_and_run_scan_job(job_id=job_id, worker_id="refresh_source_direct")
    return res if res is not None else _summary(source_id, "already_running")


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
    "STATUS_COMPLETED",
    "STATUS_FAILED",
    "STATUS_PARTIAL",
    "STATUS_PAUSED",
    "STATUS_PAUSED_QUOTA",
    "STATUS_PENDING",
    "STATUS_RUNNING",
    "STOP_REASON_END_OF_RESULTS",
    "STOP_REASON_ERROR",
    "STOP_REASON_KNOWN_REELS_REACHED",
    "STOP_REASON_MAX_PAGES_REACHED",
    "STOP_REASON_QUOTA_EXHAUSTED",
    "STOP_REASON_SAFETY_LIMIT",
    "can_start_import",
    "claim_and_run_scan_job",
    "execute_scan_job",
    "initial_import",
    "list_source_inventory",
    "queue_scan_job",
    "quota_status",
    "recover_incomplete_scan_jobs",
    "refresh_source",
    "scan_source_self_hosted",
]
