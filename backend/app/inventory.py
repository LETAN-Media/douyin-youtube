import logging
import threading
from datetime import datetime, timezone
from typing import Any

import yt_dlp
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.douyin_inventory_providers import (
    AUTH_REQUIRED_MESSAGE,
    DouyinAuthRequiredError,
    discover_profile_videos,
)
from app.models import DouyinSource, DouyinVideo, Pipeline

logger = logging.getLogger("douyin-youtube-inventory")

_inventory_semaphore: threading.Semaphore | None = None
_inventory_semaphore_size: int | None = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_semaphore() -> threading.Semaphore:
    global _inventory_semaphore, _inventory_semaphore_size
    try:
        size = int(getattr(settings, "douyin_inventory_concurrency", 1) or 1)
    except (TypeError, ValueError):
        size = 1
    size = max(1, min(size, 4))
    if _inventory_semaphore is None or _inventory_semaphore_size != size:
        _inventory_semaphore = threading.Semaphore(size)
        _inventory_semaphore_size = size
    return _inventory_semaphore


def extract_video_id_from_url(url: str | None) -> str | None:
    if not url:
        return None

    match = __import__("re").search(r'/video/(\d+)', url)
    if match:
        return match.group(1)

    match = __import__("re").search(r'v\.douyin\.com/([a-zA-Z0-9]+)', url)
    if match:
        return match.group(1)

    return None


def fetch_all_videos_from_source(
    profile_url: str,
    source_id: str,
) -> list[dict[str, Any]]:
    """Legacy yt-dlp listing kept as LAST fallback (and for tests).

    Primary discovery lives in app.douyin_inventory_providers.
    Never downloads MP4 (download=False).
    """
    if not profile_url:
        return []

    yt_dlp_options = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "socket_timeout": 30,
        "retries": 2,
        "fragment_retries": 2,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/18.0 Mobile/15E148 Safari/604.1"
            ),
        },
    }

    videos: list[dict[str, Any]] = []

    try:
        with yt_dlp.YoutubeDL(yt_dlp_options) as ydl:
            info = ydl.extract_info(
                profile_url,
                download=False,
            )

            if info is None:
                return videos

            entries = info.get("entries") or []
            if not entries and info.get("_type") == "video":
                entries = [info]

            for entry in entries:
                if not isinstance(entry, dict):
                    continue

                video_url = entry.get("url") or entry.get("webpage_url") or entry.get("original_url")
                video_id = (
                    extract_video_id_from_url(video_url)
                    or entry.get("id")
                    or entry.get("display_id")
                )

                if not video_id:
                    continue

                title = str(entry.get("title") or entry.get("description") or "").strip()
                description = str(entry.get("description") or "").strip()

                upload_date = None
                timestamp = entry.get("timestamp")
                if isinstance(timestamp, (int, float)) and timestamp > 0:
                    upload_date = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                else:
                    upload_date_str = str(entry.get("upload_date") or "")
                    if upload_date_str and len(upload_date_str) == 8:
                        try:
                            year = int(upload_date_str[0:4])
                            month = int(upload_date_str[4:6])
                            day = int(upload_date_str[6:8])
                            upload_date = datetime(year, month, day, tzinfo=timezone.utc)
                        except ValueError:
                            upload_date = None

                videos.append({
                    "video_id": str(video_id),
                    "title": title[:200],
                    "description": description[:1000],
                    "url": str(video_url or profile_url),
                    "douyin_created_at": upload_date,
                })

    except Exception as exc:
        logger.warning(
            "Failed to fetch videos from source=%s profile=%s: %s",
            source_id,
            profile_url,
            exc,
        )

    return videos


def _set_source_state(
    db: Session,
    source_id: str,
    *,
    status: str,
    error: str | None = None,
    count: int | None = None,
    last_video_id: str | None = None,
) -> None:
    source = db.get(DouyinSource, source_id)
    if source is None:
        return
    source.inventory_sync_status = status
    source.inventory_sync_error = error
    if count is not None:
        source.inventory_count = int(count)
    if last_video_id is not None:
        source.last_video_id = last_video_id
    if status in ("completed", "auth_required", "failed"):
        source.inventory_synced_at = utcnow()
        source.last_checked_at = utcnow()
        source.last_scan_at = utcnow()
        # Manual-inventory mode: do NOT schedule the next douyin scan. Nothing
        # is due automatically, so the monitor cannot spend RapidAPI quota in
        # the background. Only an explicit opt-in restores scheduling.
        if getattr(settings, "douyin_auto_scan_enabled", False):
            try:
                interval = int(source.scan_interval_minutes or 15)
            except (TypeError, ValueError):
                interval = 15
            source.next_scan_at = utcnow() + __import__("datetime").timedelta(
                minutes=max(5, interval)
            )
    db.commit()


def _apply_baseline_policy(
    db: Session,
    *,
    source: DouyinSource,
) -> None:
    """First-sync policy: NEW_ONLY baselines everything (no historic uploads);
    LAST_N keeps the newest N videos active, baselines the rest."""
    if source.baseline_done:
        return
    candidates = db.execute(
        select(DouyinVideo)
        .where(DouyinVideo.source_id == source.id)
        .where(DouyinVideo.status.in_(["new", "backlog"]))
        .order_by(DouyinVideo.douyin_created_at.desc())
    ).scalars().all()
    mode = (source.start_mode or "new_only").lower()
    keep_ids: set[str] = set()
    if mode == "last_n":
        try:
            limit = max(1, int(source.initial_limit or 10))
        except (TypeError, ValueError):
            limit = 10
        # videos without a timestamp sort last; keep discovery-fresh ones.
        with_ts = [v for v in candidates if v.douyin_created_at]
        without_ts = [v for v in candidates if not v.douyin_created_at]
        ordered = with_ts + without_ts
        keep_ids = {v.id for v in ordered[:limit]}
    for video in candidates:
        if video.id not in keep_ids:
            video.status = "baseline"
    source.baseline_done = True
    db.commit()


def _upsert_videos(
    db: Session,
    *,
    source: DouyinSource,
    pipeline: Pipeline,
    videos: list[dict[str, Any]],
    backfill: bool,
) -> tuple[int, int]:
    now = utcnow()
    threshold_days = pipeline.backlog_threshold_days or 7
    threshold_date = now - __import__("datetime").timedelta(days=threshold_days)

    new_count = 0
    updated_count = 0

    for video in videos:
        video_id = str(video.get("video_id") or "").strip()
        if not video_id:
            continue
        existing = db.execute(
            select(DouyinVideo)
            .where(
                DouyinVideo.source_id == source.id,
                DouyinVideo.video_id == video_id,
            )
            .limit(1)
        ).scalar_one_or_none()

        douyin_created_at = video.get("douyin_created_at")
        is_backlog = False
        if douyin_created_at and douyin_created_at < threshold_date:
            is_backlog = True

        title = str(video.get("title") or "")[:200]
        description = str(video.get("description") or "")[:1000]
        url = str(video.get("url") or "")

        if existing is not None:
            existing.title = title
            existing.description = description
            existing.url = url
            existing.douyin_created_at = douyin_created_at
            existing.is_backlog = is_backlog
            if existing.status == "inventory":
                existing.status = "backlog" if is_backlog else "new"
            updated_count += 1
        else:
            # Continuous monitor inserts genuinely new videos as status=new
            # with is_backfill=False. Initial full scans mark is_backfill=True.
            status = "new" if (not backfill and not is_backlog) else (
                "backlog" if is_backlog else "new"
            )
            db.add(DouyinVideo(
                source_id=source.id,
                pipeline_id=pipeline.id,
                video_id=video_id,
                title=title,
                description=description,
                url=url,
                douyin_created_at=douyin_created_at,
                status=status,
                is_backlog=is_backlog,
                is_backfill=bool(backfill),
            ))
            new_count += 1

    return new_count, updated_count


def sync_source_inventory(
    source_id: str,
    mode: str = "full",
) -> dict[str, int]:
    """Full initial sync (mode='full') or lightweight monitor (mode='latest').

    Never silently returns completed with 0 when cookies are missing:
    sets status='auth_required' with a clear error instead.
    """
    full = mode != "latest"

    with SessionLocal() as db:
        source = db.get(DouyinSource, source_id)
        if source is None:
            return {"new": 0, "updated": 0}
        if not source.enabled:
            return {"new": 0, "updated": 0}
        pipeline_id = source.pipeline_id
        profile_url = source.profile_url or ""
        sec_uid = source.douyin_sec_uid or source.douyin_user_id or ""
        if sec_uid and not profile_url:
            profile_url = f"https://www.douyin.com/user/{sec_uid}"
        if not profile_url and not sec_uid:
            logger.info("Source %s has no profile_url, skipping", source.id)
            return {"new": 0, "updated": 0}
        pipeline = db.get(Pipeline, pipeline_id) if pipeline_id else None
        if pipeline is None:
            logger.warning("Source %s has no pipeline, skipping", source.id)
            return {"new": 0, "updated": 0}
        if not pipeline.enabled:
            logger.info(
                "Pipeline %s is disabled, skipping source %s",
                pipeline.id,
                source.id,
            )
            return {"new": 0, "updated": 0}
        source.inventory_sync_status = "running"
        source.inventory_sync_error = None
        db.commit()

    semaphore = _get_semaphore()
    acquired = semaphore.acquire(blocking=False)
    if not acquired:
        logger.info("Inventory scan already running, skipping source=%s", source_id)
        return {"new": 0, "updated": 0}

    try:
        # Global PlatformAccount only — no per-source cookie.
        cookie_jar: list[dict[str, Any]] | None = None
        try:
            from app.platform_accounts import load_platform_cookie_jar

            cookie_jar = load_platform_cookie_jar("douyin")
        except Exception:
            logger.warning(
                "Platform cookie load failed for source=%s; continuing",
                source_id,
            )
            cookie_jar = None
        try:
            videos, provider = discover_profile_videos(
                profile_url, sec_uid, source_id, full=full,
                cookie_jar=cookie_jar,
            )
        except DouyinAuthRequiredError as exc:
            with SessionLocal.begin() as db:
                _set_source_state(
                    db, source_id, status="auth_required",
                    error=str(exc) or AUTH_REQUIRED_MESSAGE,
                )
                # Mark global PlatformAccount as needs reauth (not per-source)
                try:
                    from app.models import PlatformAccount

                    acct = db.execute(
                        __import__("sqlalchemy").select(PlatformAccount).where(
                            PlatformAccount.platform == "douyin"
                        ).limit(1)
                    ).scalar_one_or_none()
                    if acct is not None:
                        acct.status = "expired"
                        acct.needs_reauth = True
                        acct.last_error = str(exc)[:500]
                except Exception:
                    pass
            logger.warning("Source %s inventory auth_required", source_id)
            return {"new": 0, "updated": 0}

        if not videos:
            # Real empty result (profile private/blocked/empty), never fake.
            # Keep prior count; mark completed only when cookies exist.
            # If the primary explicitly needed auth it already returned above.
            with SessionLocal.begin() as db:
                source = db.get(DouyinSource, source_id)
                if source is None:
                    return {"new": 0, "updated": 0}
                source.inventory_sync_status = "completed"
                source.inventory_sync_error = None
                source.inventory_synced_at = utcnow()
                source.last_checked_at = utcnow()
                logger.info(
                    "No videos found for source=%s via provider=%s",
                    source.id,
                    provider,
                )
            return {"new": 0, "updated": 0}

        with SessionLocal.begin() as db:
            source = db.get(DouyinSource, source_id)
            if source is None:
                return {"new": 0, "updated": 0}
            pipeline = db.get(Pipeline, source.pipeline_id) if source.pipeline_id else None
            if pipeline is None:
                return {"new": 0, "updated": 0}
            new_count, updated_count = _upsert_videos(
                db, source=source, pipeline=pipeline,
                videos=videos, backfill=full,
            )
            _apply_baseline_policy(db, source=source)
            if videos:
                source.last_video_id = str(videos[0].get("video_id") or "")
            total = db.execute(
                select(func.count(DouyinVideo.id)).where(
                    DouyinVideo.source_id == source.id
                )
            ).scalar_one_or_none() or 0
            source.inventory_count = int(total)
            source.inventory_sync_status = "completed"
            source.inventory_sync_error = None
            source.inventory_synced_at = utcnow()
            source.last_checked_at = utcnow()

        logger.info(
            "Source %s inventory sync via %s: %s new, %s updated",
            source_id,
            provider,
            new_count,
            updated_count,
        )
        return {"new": new_count, "updated": updated_count}
    except DouyinAuthRequiredError as exc:
        with SessionLocal.begin() as db:
            _set_source_state(
                db, source_id, status="auth_required",
                error=str(exc) or AUTH_REQUIRED_MESSAGE,
            )
        return {"new": 0, "updated": 0}
    except Exception as exc:
        logger.exception("Inventory sync failed for source %s", source_id)
        with SessionLocal.begin() as db:
            _set_source_state(
                db, source_id, status="failed", error=str(exc)[:2000],
            )
        return {"new": 0, "updated": 0}
    finally:
        try:
            semaphore.release()
        except Exception:
            pass


def sync_pipeline_inventory(pipeline_id: str) -> dict[str, int]:
    with SessionLocal() as db:
        sources = db.execute(
            select(DouyinSource)
            .where(DouyinSource.pipeline_id == pipeline_id)
            .where(DouyinSource.enabled == True)
            .order_by(DouyinSource.created_at.asc())
        ).scalars().all()

    total_new = 0
    total_updated = 0

    for source in sources:
        result = sync_source_inventory(source.id, mode="full")
        total_new += result["new"]
        total_updated += result["updated"]

    return {"new": total_new, "updated": total_updated}


def run_inventory_sync() -> None:
    with SessionLocal() as db:
        pipelines = db.execute(
            select(Pipeline)
            .where(Pipeline.enabled == True)
        ).scalars().all()

    for pipeline in pipelines:
        try:
            sync_pipeline_inventory(pipeline.id)
        except Exception:
            logger.exception("Inventory sync failed for pipeline %s", pipeline.id)
