"""Publish worker: claims scheduled/pending queue items and publishes to Facebook."""
import logging
from datetime import datetime, timedelta, timezone

import httpx

from ..config import settings
from ..db.repositories import facebook_pages as fb_repo
from ..db.repositories import history as history_repo
from ..db.repositories import queue as queue_repo
from ..db.models import MediaPublishStatus, MediaStatus, PublicationOutcome, QueueStatus
from . import facebook_publisher as facebook_pub
from . import media as media_service
from .ai_rate_limiter import AIRateLimiter
from .ai import enrich_metadata, AIError
from .scheduler import can_publish_today, ensure_today_schedule

logger = logging.getLogger("backend-youtube.publish_worker")


class PublishWorker:
    def __init__(self, worker_id: str = "publish-worker-0"):
        self.worker_id = worker_id
        self._client: httpx.AsyncClient | None = None
        self._rate_limiter = AIRateLimiter()

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(max_connections=50, max_keepalive_connections=10)
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0), limits=limits)
        return self._client

    async def run_once(self, session, pipeline, limit: int = 1) -> int:
        if not pipeline.auto_publish:
            return 0
        await ensure_today_schedule(session, pipeline.id)
        now = datetime.now(tz=timezone.utc)
        items = await queue_repo.claim_next(
            session,
            pipeline.id,
            self.worker_id,
            concurrency=settings.PUBLISH_CONCURRENCY,
            stale_ttl=settings.PUBLISH_STALE_TTL_SECONDS,
            now=now,
        )
        published = 0
        for item in items:
            try:
                await self._process_item(session, pipeline, item)
                published += 1
            except Exception as exc:
                logger.exception("Publish item %s failed: %s", item.id, exc)
                await queue_repo.set_queue_status(session, item.id, QueueStatus.FAILED, last_error=str(exc), retry_count=item.retry_count + 1)
        return published

    async def _process_item(self, session, pipeline, item) -> None:
        from ..db.repositories import jobs as job_repo
        if await queue_repo.is_already_queued(session, pipeline.id, item.youtube_video_id, item.facebook_page_id) and item.status == QueueStatus.PROCESSING:
            pass
        already = await history_repo.is_already_published(session, pipeline.id, item.youtube_video_id, item.facebook_page_id)
        if already:
            await queue_repo.set_queue_status(session, item.id, QueueStatus.PUBLISHED)
            await history_repo.create_publication_history(
                session,
                pipeline_id=pipeline.id,
                youtube_video_id=item.youtube_video_id,
                facebook_page_id=pipeline.default_facebook_page_id or item.facebook_page_id,
                status=PublicationOutcome.SUCCESS,
                publish_mode=item.publish_mode,
                published_at=datetime.now(tz=timezone.utc),
                is_update=True,
            )
            return

        media = await self._ensure_media(session, pipeline, item)
        caption, hashtags, title, description = await self._compose_caption(session, pipeline, item, media)
        token = await fb_repo.decrypt_page_token(session, item.facebook_page_id)
        if not token:
            await self._fail(session, item, "Facebook page token not available")
            return
        client = await self.get_client()
        if not await self._check_quota_and_slot(session, pipeline):
            await queue_repo.set_queue_status(session, item.id, QueueStatus.SCHEDULED, reservation_token=None)
            return
        mode = item.publish_mode
        try:
            result = await facebook_pub.publish(session, client, token, pipeline, item, media, caption, hashtags, title, description, mode)
        except facebook_pub.FacebookError as exc:
            await self._handle_failure(session, pipeline, item, str(exc))
            return
        await history_repo.create_publication_history(
            session,
            pipeline_id=pipeline.id,
            youtube_video_id=item.youtube_video_id,
            facebook_page_id=item.facebook_page_id,
            media_file_id=getattr(item, "media_file_id", None),
            facebook_post_id=result.get("id"),
            facebook_video_id=result.get("facebook_video_id"),
            facebook_reel_id=result.get("facebook_reel_id"),
            publish_mode=mode,
            status=PublicationOutcome.SUCCESS,
            ai_caption=caption,
            ai_enhanced=item.ai_enhanced,
            title=title,
            description=description,
            published_at=datetime.now(tz=timezone.utc),
        )
        await queue_repo.set_queue_status(session, item.id, QueueStatus.PUBLISHED, facebook_post_id=result.get("id"))
        await media_service.cleanup(media.local_path)

    async def _ensure_media(self, session, pipeline, item):
        from ..db.repositories import facebook_pages as _fb
        from ..db.repositories.media_files import get_ready_media_for_video, create_media_file, update_media_status
        media = await get_ready_media_for_video(session, pipeline.id, item.youtube_video_id)
        if media is not None:
            item.media_file_id = media.id
            await session.flush()
            return media
        raise facebook_pub.FacebookError("No ready media file for video; ensure media acquisition ran first")

    async def _compose_caption(self, session, pipeline, item, media):
        from ..db.repositories import ai_metadata as ai_repo
        meta = await ai_repo.get_ai_metadata(session, pipeline.id, item.youtube_video_id)
        if meta and meta.caption:
            caption = meta.caption
            hashtags = meta.hashtags or []
            title = meta.title_suggestion or item.title
            description = meta.description_suggestion or media.raw  # type: ignore
            description = None
            enhanced = meta.enhanced
        else:
            caption = item.ai_caption or item.title
            hashtags = []
            title = item.title
            description = item.description
            enhanced = item.ai_enhanced
        return caption, hashtags, title, description

    async def _check_quota_and_slot(self, session, pipeline) -> bool:
        now = datetime.now(tz=timezone.utc)
        if not await can_publish_today(session, pipeline, now):
            return False
        return True

    async def _fail(self, session, item, message: str, retry: bool = True) -> None:
        item.retry_count += 1
        if retry and item.retry_count < settings.RETRY_MAX_ATTEMPTS:
            next_attempt = datetime.now(tz=timezone.utc) + timedelta(seconds=settings.RETRY_BASE_BACKOFF_SECONDS * (2 ** min(item.retry_count, 6)))
            await queue_repo.set_queue_status(session, item.id, QueueStatus.SCHEDULED, scheduled_for=next_attempt, last_error=message)
        else:
            await queue_repo.set_queue_status(session, item.id, QueueStatus.FAILED, last_error=message, error_code="max_retries_exceeded")

    async def _handle_failure(self, session, pipeline, item, message: str) -> None:
        logger.warning("Publish failure for %s: %s", item.id, message)
        await self._fail(session, item, message, retry=True)

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
