"""Background worker runner: schedules polling for scheduler/publish/ai/scan."""
import asyncio
import logging

from ..config import settings
from ..db.repositories import pipelines as pipeline_repo

logger = logging.getLogger("backend-youtube.workers")


class WorkerManager:
    def __init__(self):
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()

    async def start(self) -> None:
        from .publish_worker import PublishWorker
        from .ai_worker import AIWorker
        from ..db.session import get_session_factory
        factory = get_session_factory()
        self._tasks = []
        if settings.PUBLISH_WORKER_ENABLED:
            self._tasks.append(asyncio.create_task(self._run_publish(factory, PublishWorker())))
        if settings.AI_WORKER_ENABLED:
            self._tasks.append(asyncio.create_task(self._run_ai(factory, AIWorker())))
        if settings.SCHEDULER_ENABLED:
            self._tasks.append(asyncio.create_task(self._run_scheduler(factory)))

    async def aclose(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks = []

    async def _run_publish(self, factory, worker) -> None:
        from ..db.repositories import pipelines as p_repo
        while not self._stop.is_set():
            async with factory() as session:
                try:
                    pipelines = await p_repo.list_pipelines(session, limit=200)
                    for pipeline in pipelines:
                        try:
                            await worker.run_once(session, pipeline, limit=1)
                        except Exception:
                            logger.exception("Publish loop error for pipeline %s", pipeline.id)
                except Exception:
                    logger.exception("Publish worker error")
            await asyncio.sleep(settings.PUBLISH_POLL_SECONDS)

    async def _run_ai(self, factory, worker) -> None:
        from ..db.repositories import pipelines as p_repo
        while not self._stop.is_set():
            async with factory() as session:
                try:
                    pipelines = await p_repo.list_pipelines(session, limit=200)
                    for pipeline in pipelines:
                        try:
                            await worker.run_once(session, pipeline, limit=1)
                        except Exception:
                            logger.exception("AI worker error for pipeline %s", pipeline.id)
                except Exception:
                    logger.exception("AI worker error")
            await asyncio.sleep(settings.AI_WORKER_POLL_SECONDS)

    async def _run_scheduler(self, factory) -> None:
        from ..services.scheduler import schedule_pending_items, ensure_today_schedule
        from ..db.repositories import pipelines as p_repo
        while not self._stop.is_set():
            async with factory() as session:
                try:
                    pipelines = await p_repo.list_pipelines(session, limit=200)
                    for pipeline in pipelines:
                        try:
                            await ensure_today_schedule(session, pipeline.id)
                            await schedule_pending_items(session, pipeline)
                        except Exception:
                            logger.exception("Scheduler error for pipeline %s", pipeline.id)
                except Exception:
                    logger.exception("Scheduler error")
            await asyncio.sleep(settings.SCHEDULER_POLL_SECONDS)


async def run_scan_pipeline(session, pipeline, source_ids: list[str] | None = None) -> dict:
    """Scan a pipeline's YouTube sources and ingest new video records."""
    import httpx
    from sqlalchemy import select as _select
    from ..db.repositories import sources as sources_repo
    from ..db.repositories import videos as videos_repo
    from ..db.models import YouTubeSource, YouTubeVideo
    from ..services.youtube_scan import YouTubeScanError, list_channel_videos
    client = httpx.AsyncClient(timeout=httpx.Timeout(settings.YOUTUBE_API_TIMEOUT), base_url="https://www.googleapis.com/youtube/v3")
    result = {"scanned": 0, "new": 0, "sources": []}
    if source_ids:
        resolved = [await session.get(YouTubeSource, sid) for sid in source_ids]
        sources = [s for s in resolved if s is not None]
    else:
        sources = await sources_repo.list_sources(session, pipeline.id)
    result["sources"] = [{"id": s.id, "channel_id": s.channel_id} for s in sources]
    for source in sources:
        channel_id = source.channel_id or source.custom_url
        if not channel_id:
            continue
        try:
            vids = await session.execute(
                _select(YouTubeVideo.video_id).where(YouTubeVideo.pipeline_id == pipeline.id)
            )
            existing = set(vids.scalars().all())
            scanned = await list_channel_videos(client, channel_id, max_results=settings.YOUTUBE_SCAN_MAX_RESULTS)
            for v in scanned:
                if v["video_id"] in existing:
                    continue
                await videos_repo.upsert_video(
                    session,
                    pipeline.id,
                    v["video_id"],
                    channel_id=v.get("channel_id"),
                    title=v.get("title"),
                    description=v.get("description"),
                    publish_time=v.get("publish_time"),
                    thumbnail_url=(v.get("thumbnails", {}) or {}).get("high", {}).get("url"),
                    view_count=v.get("view_count"),
                    like_count=v.get("like_count"),
                    tags=v.get("tags"),
                    raw=v.get("raw"),
                    is_insert_only=True,
                )
                result["scanned"] += 1
                result["new"] += 1
            await sources_repo.touch_source_scan(session, source.id)
        except YouTubeScanError as exc:
            await sources_repo.set_source_error(session, source.id, str(exc))
            logger.warning("Scan failed for source %s: %s", source.id, exc)
        except Exception as exc:
            logger.exception("Unexpected scan error for source %s: %s", source.id, exc)
    await client.aclose()
    return result
