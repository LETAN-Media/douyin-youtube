import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import yt_dlp
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.inventory import sync_source_inventory
from app.models import DouyinSource, Pipeline

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


def fetch_latest_videos_from_source(
    profile_url: str,
    source_id: str,
) -> list[dict[str, Any]]:
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
            source_id,
            profile_url,
            exc,
        )

    return videos


def _build_source_context(profile_url: str, videos: list[dict[str, Any]]) -> str:
    parts = [f"profile_url: {profile_url}"]

    for video in videos[:5]:
        title = video.get("title", "")
        desc = video.get("description", "")
        if title:
            parts.append(f"video_title: {title}")
        if desc:
            parts.append(f"video_description: {desc}")

    return "\n".join(parts)[:6000]


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
            if not source.enabled:
                continue

            pipeline_id = source.pipeline_id
            profile_url = source.profile_url or ""
            user_id = source.douyin_sec_uid or source.douyin_user_id or ""

            if user_id and not profile_url:
                profile_url = f"https://www.douyin.com/user/{user_id}"

            if not profile_url:
                logger.info("Source %s has no profile_url, skipping", source.id)
                continue

            pipeline = None
            if pipeline_id:
                with SessionLocal() as pipeline_db:
                    pipeline = pipeline_db.get(Pipeline, pipeline_id)

            if pipeline is None:
                logger.warning("Source %s has no pipeline, skipping", source.id)
                continue

            if not pipeline.enabled:
                logger.info("Pipeline %s is disabled, skipping source %s", pipeline.id, source.id)
                continue

            logger.info("Checking source=%s pipeline=%s profile=%s", source.id, pipeline.id, profile_url)

            sync_source_inventory(source.id)

        except Exception:
            logger.exception("Failed to process source=%s", source.id)


async def monitor_loop() -> None:
    if not getattr(settings, "monitor_enabled", True):
        logger.info("Douyin source monitor is disabled")
        return

    startup_delay = getattr(settings, "monitor_startup_delay_seconds", 10)
    poll_interval = getattr(settings, "monitor_poll_seconds", 300)

    logger.info("Douyin source monitor started, waiting %s seconds before first run", startup_delay)
    await asyncio.sleep(startup_delay)

    while True:
        try:
            logger.info("Starting monitor cycle")
            await asyncio.to_thread(run_monitor_once)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Monitor loop error")

        logger.info("Monitor sleeping for %s seconds", poll_interval)
        await asyncio.sleep(poll_interval)
