import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import yt_dlp
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import DouyinSource, Pipeline, VideoJob

logger = logging.getLogger("douyin-youtube-monitor")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def extract_video_id_from_url(url: str | None) -> str | None:
    if not url:
        return None

    match = re.search(r'/video/(\d+)', url)
    if match:
        return match.group(1)

    match = re.search(r'v\.douyin\.com/([a-zA-Z0-9]+)', url)
    if match:
        return match.group(1)

    return None


def fetch_latest_videos_from_source(source: DouyinSource) -> list[dict[str, Any]]:
    if not source.profile_url and not source.douyin_sec_uid:
        return []

    profile_url = source.profile_url or ""
    user_id = source.douyin_sec_uid or source.douyin_user_id or ""

    if user_id and not profile_url:
        profile_url = f"https://www.douyin.com/user/{user_id}"

    if not profile_url:
        return []

    yt_dlp_options = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "playlistend": 10,
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

                videos.append({
                    "video_id": str(video_id),
                    "title": title[:200],
                    "description": description[:1000],
                    "url": str(video_url or profile_url),
                })

    except Exception as exc:
        logger.warning(
            "Failed to fetch videos from source=%s profile=%s: %s",
            source.id,
            profile_url,
            exc,
        )

    return videos


def already_processed(db: Session, source_id: str, video_id: str) -> bool:
    existing = db.execute(
        select(VideoJob)
        .where(
            VideoJob.pipeline_id == source_id,
            VideoJob.source_video_id == video_id,
        )
        .limit(1)
    ).scalar_one_or_none()

    return existing is not None


def process_source(source: DouyinSource) -> None:
    if not source.enabled:
        return

    pipeline = source.pipeline
    if pipeline is None:
        logger.warning("Source %s has no pipeline", source.id)
        return

    if not pipeline.enabled:
        logger.info("Pipeline %s is disabled, skipping source %s", pipeline.id, source.id)
        return

    logger.info("Checking source=%s pipeline=%s", source.id, pipeline.id)

    videos = fetch_latest_videos_from_source(source)
    if not videos:
        logger.info("No videos found for source=%s", source.id)
        return

    new_count = 0

    with SessionLocal.begin() as db:
        for video in videos:
            video_id = video["video_id"]

            if already_processed(db, source.id, video_id):
                continue

            title = video.get("title") or ""
            description = video.get("description") or video.get("url") or ""

            job = VideoJob(
                source_url=video.get("url") or source.profile_url or "",
                source_title=title,
                title=None,
                description=description,
                privacy_status=pipeline.default_privacy,
                status="pending",
                pipeline_id=pipeline.id,
                source_video_id=video_id,
            )

            db.add(job)
            new_count += 1

        source.last_checked_at = utcnow()
        if videos:
            source.last_video_id = videos[0]["video_id"]

    logger.info(
        "Source %s produced %s new jobs",
        source.id,
        new_count,
    )


def run_monitor_once() -> None:
    with SessionLocal() as db:
        sources = db.execute(
            select(DouyinSource)
            .where(DouyinSource.enabled == True)  # noqa: E712
            .order_by(DouyinSource.created_at.asc())
        ).scalars().all()

    logger.info("Monitoring %s enabled sources", len(sources))

    for source in sources:
        try:
            process_source(source)
        except Exception:
            logger.exception("Failed to process source=%s", source.id)


async def monitor_loop() -> None:
    logger.info("Douyin source monitor started")

    while True:
        try:
            run_monitor_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Monitor loop error")

        await asyncio.sleep(
            getattr(settings, "monitor_poll_seconds", 300)
        )
