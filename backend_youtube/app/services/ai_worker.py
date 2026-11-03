"""AI worker: enriches captions for queued items needing AI processing."""
import logging
from datetime import datetime, timezone

from ..db.repositories import ai_metadata as ai_repo
from ..db.repositories import queue as queue_repo
from ..db.repositories.queue import claim_next
from ..db.models import QueueStatus
from .ai import enrich_metadata, AIError
from .ai_rate_limiter import AIRateLimiter
from .scheduler import ensure_today_schedule

logger = logging.getLogger("backend-youtube.ai_worker")


class AIWorker:
    def __init__(self, worker_id: str = "ai-worker-0"):
        self.worker_id = worker_id
        self._rate_limiter = AIRateLimiter()

    async def run_once(self, session, pipeline, limit: int = 1) -> int:
        from ..db.repositories import media_files as media_repo
        if not pipeline.ai_strategy or pipeline.ai_strategy == "off":
            return 0
        items = await queue_repo.list_queue(session, pipeline.id, limit=100, status=QueueStatus.PENDING)
        processed = 0
        for item in items:
            if item.ai_caption and item.ai_enhanced:
                continue
            media = await media_repo.get_media_file(session, item.media_file_id) if item.media_file_id else None
            if media is None:
                continue
            try:
                result = await enrich_metadata(
                    self._rate_limiter,
                    youtube_video_id=item.youtube_video_id,
                    title=item.title or media.title,
                    description=item.description,
                    duration_seconds=media.duration_seconds,
                    view_count=None,
                    tags=None,
                    strategy=pipeline.ai_strategy or "auto",
                )
            except AIError as exc:
                logger.warning("AI enrichment failed for %s: %s", item.id, exc)
                await queue_repo.set_queue_status(session, item.id, QueueStatus.FAILED, last_error=str(exc))
                continue
            from ..db.repositories import ai_metadata as ai_repo_mod
            await ai_repo_mod.upsert_ai_metadata(
                session,
                pipeline.id,
                item.youtube_video_id,
                strategy=pipeline.ai_strategy,
                model=pipeline.ai_model,
                enhanced=True,
                caption=result.get("caption"),
                hashtags=result.get("hashtags"),
                title_suggestion=result.get("title_suggestion"),
                description_suggestion=result.get("description_suggestion"),
                raw_response=result,
            )
            processed += 1
        return processed
