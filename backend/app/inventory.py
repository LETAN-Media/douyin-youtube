import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import yt_dlp
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import DouyinSource, DouyinVideo, Pipeline

logger = logging.getLogger("douyin-youtube-inventory")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


def sync_source_inventory(source_id: str) -> dict[str, int]:
    with SessionLocal() as db:
        source = db.get(DouyinSource, source_id)
        if source is None:
            return {"new": 0, "updated": 0}

        if not source.enabled:
            return {"new": 0, "updated": 0}

        pipeline_id = source.pipeline_id
        profile_url = source.profile_url or ""
        user_id = source.douyin_sec_uid or source.douyin_user_id or ""

        if user_id and not profile_url:
            profile_url = f"https://www.douyin.com/user/{user_id}"

        if not profile_url:
            logger.info("Source %s has no profile_url, skipping", source.id)
            return {"new": 0, "updated": 0}

        pipeline = None
        if pipeline_id:
            pipeline = db.get(Pipeline, pipeline_id)

        if pipeline is None:
            logger.warning("Source %s has no pipeline, skipping", source.id)
            return {"new": 0, "updated": 0}

        if not pipeline.enabled:
            logger.info("Pipeline %s is disabled, skipping source %s", pipeline.id, source.id)
            return {"new": 0, "updated": 0}

    videos = fetch_all_videos_from_source(profile_url, source.id)
    if not videos:
        logger.info("No videos found for source=%s", source.id)
        return {"new": 0, "updated": 0}

    new_count = 0
    updated_count = 0

    with SessionLocal.begin() as db:
        now = utcnow()
        threshold_days = pipeline.backlog_threshold_days or 7
        threshold_date = now - __import__("datetime").timedelta(days=threshold_days)

        for video in videos:
            video_id = video["video_id"]
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

            if existing is not None:
                existing.title = video.get("title", "")
                existing.description = video.get("description", "")
                existing.url = video.get("url", "")
                existing.douyin_created_at = douyin_created_at
                existing.is_backlog = is_backlog
                if existing.status == "inventory":
                    existing.status = "backlog" if is_backlog else "new"
                updated_count += 1
            else:
                status = "backlog" if is_backlog else "new"
                db.add(DouyinVideo(
                    source_id=source.id,
                    pipeline_id=pipeline.id,
                    video_id=video_id,
                    title=video.get("title", ""),
                    description=video.get("description", ""),
                    url=video.get("url", ""),
                    douyin_created_at=douyin_created_at,
                    status=status,
                    is_backlog=is_backlog,
                ))
                new_count += 1

        db.execute(
            __import__("sqlalchemy")
            .update(DouyinSource)
            .where(DouyinSource.id == source.id)
            .values(
                last_checked_at=now,
                last_video_id=videos[0]["video_id"],
            )
        )

    logger.info(
        "Source %s inventory sync: %s new, %s updated",
        source.id,
        new_count,
        updated_count,
    )

    return {"new": new_count, "updated": updated_count}


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
        result = sync_source_inventory(source.id)
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
