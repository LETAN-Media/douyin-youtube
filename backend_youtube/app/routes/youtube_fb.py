from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.db.session import get_session
from app.db.repositories import pipelines as pipeline_repo
from app.db.repositories import facebook_pages as fb_repo
from app.db.repositories import queue as queue_repo
from app.db.repositories import history as history_repo
from app.db.repositories import schedules as sched_repo
from app.db.repositories import ai_metadata as ai_repo
from app.dto import (
    FacebookPageCreate,
    FacebookPageRead,
    ManualPublishRequest,
    PublicationRead,
    QueueItemRead,
    ScanRequest,
    ScheduleRead,
    SourceRead,
)
from app.services.media import acquire_media, MediaError
from app.services.publish import publish as do_publish
from app.services.workers import run_scan_pipeline
from app.services.youtube_scan import get_channel_id_by_handle, enrich_video_stats
from app.utils import decrypt_token, gen_id

router = APIRouter()


@router.get("/pipelines/{pipeline_id}/facebook-pages", response_model=list[FacebookPageRead])
async def list_pages(pipeline_id: str, session: AsyncSession = Depends(get_session)):
    if await pipeline_repo.get_pipeline(session, pipeline_id) is None:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Pipeline not found"})
    rows = await fb_repo.list_facebook_pages(session, pipeline_id)
    return [_page_read(p) for p in rows]


@router.post("/pipelines/{pipeline_id}/facebook-pages", response_model=FacebookPageRead)
async def add_page(pipeline_id: str, payload: FacebookPageCreate, session: AsyncSession = Depends(get_session)):
    if await pipeline_repo.get_pipeline(session, pipeline_id) is None:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Pipeline not found"})
    try:
        page = await fb_repo.add_facebook_page(
            session, pipeline_id, page_id=payload.page_id, page_name=payload.page_name,
            page_access_token=payload.page_access_token, scopes=payload.scopes, is_default=payload.is_default,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"error": "DB_ERROR", "message": str(exc)})
    return _page_read(page)


@router.post("/pipelines/{pipeline_id}/facebook-pages/set-default")
async def set_default_page(pipeline_id: str, page_row_id: str, session: AsyncSession = Depends(get_session)):
    ok = await fb_repo.set_default_facebook_page(session, pipeline_id, page_row_id)
    if not ok:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Page not found"})
    return {"ok": True}


@router.post("/pipelines/{pipeline_id}/scan")
async def trigger_scan(pipeline_id: str, payload: ScanRequest, session: AsyncSession = Depends(get_session)):
    pipeline = await pipeline_repo.get_pipeline(session, pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Pipeline not found"})
    result = await run_scan_pipeline(session, pipeline, source_ids=payload.source_ids)
    return {"scanned": result["scanned"], "new": result["new"], "sources": result["sources"]}


@router.post("/pipelines/{pipeline_id}/manual")
async def manual_publish(pipeline_id: str, payload: ManualPublishRequest, session: AsyncSession = Depends(get_session)):
    pipeline = await pipeline_repo.get_pipeline(session, pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Pipeline not found"})
    video_id = _extract_video_id(payload.youtube_url)
    if not video_id:
        raise HTTPException(status_code=400, detail={"error": "INVALID_URL", "message": "Could not extract YouTube video id"})
    from app.services.youtube_scan import enrich_video_stats
    import httpx
    async with httpx.AsyncClient() as client:
        try:
            stats = await enrich_video_stats(client, [video_id])
        except Exception:
            stats = {}
    from app.db.repositories import videos as videos_repo
    video = await videos_repo.get_video(session, video_id)
    if video is None:
        await videos_repo.upsert_video(session, pipeline_id, video_id, title=payload.title)
        video = await videos_repo.get_video(session, video_id)
    try:
        media = await acquire_media(video_id, payload.youtube_url)
    except MediaError as exc:
        raise HTTPException(status_code=400, detail={"error": "MEDIA_ERROR", "message": str(exc)})
    from app.db.repositories import media_files as media_repo
    mf = await media_repo.create_media_file(
        session, pipeline_id, video_id, status="ready", resolution=media.resolution, width=media.width, height=media.height,
        duration_seconds=media.duration_seconds, file_size_bytes=media.file_size_bytes, mime_type=media.mime_type,
        local_path=media.local_path, provider=media.provider, provider_id=media.provider_id,
    )
    page_row_id = payload.facebook_page_id
    caption = payload.caption
    if payload.use_ai_caption and pipeline.ai_strategy != "off":
        try:
            from app.services.ai import enrich_metadata, AIError
            from app.services.ai_rate_limiter import AIRateLimiter
            limiter = AIRateLimiter()
            meta = await enrich_metadata(
                limiter, youtube_video_id=video_id, title=media.title or payload.title, description=payload.description,
                duration_seconds=media.duration_seconds, view_count=None, tags=None, strategy=pipeline.ai_strategy or "auto",
            )
            caption = meta.get("caption") or caption
        except AIError as exc:
            pass
    if payload.schedule_for:
        scheduled_for = payload.schedule_for
        mode = "scheduled"
    else:
        scheduled_for = None
        already = await history_repo.is_already_published(session, pipeline_id, video_id, page_row_id)
        if already:
            return {"status": "already_published", "video_id": video_id}
        item = await queue_repo.enqueue(
            session, pipeline_id=pipeline_id, youtube_video_id=video_id, facebook_page_id=page_row_id,
            media_file_id=mf.id, ai_caption=caption, title=payload.title, description=payload.description,
            scheduled_for=scheduled_for, priority=100,
        )
        try:
            worker_result = await _publish_now(session, pipeline, item, media, caption, payload)
        except Exception as exc:
            await queue_repo.set_queue_status(session, item.id, "failed", last_error=str(exc))
            raise HTTPException(status_code=500, detail={"error": "PUBLISH_FAILED", "message": str(exc)})
        return {"status": "published", "video_id": video_id, "result": worker_result}
    item = await queue_repo.enqueue(
        session, pipeline_id=pipeline_id, youtube_video_id=video_id, facebook_page_id=page_row_id,
        media_file_id=mf.id, ai_caption=caption, title=payload.title, description=payload.description,
        scheduled_for=scheduled_for, priority=100,
    )
    return {"status": "scheduled", "video_id": video_id, "queue_item_id": item.id, "scheduled_for": scheduled_for}


async def _publish_now(session, pipeline, item, media, caption, payload) -> dict:
    token = await fb_repo.decrypt_page_token(session, item.facebook_page_id)
    import httpx
    async with httpx.AsyncClient() as client:
        result = await do_publish(
            session, client, token, pipeline, item, media, caption, [], payload.title, payload.description, payload.publish_mode,
        )
    await history_repo.create_publication_history(
        session, pipeline_id=pipeline.id, youtube_video_id=item.youtube_video_id, facebook_page_id=item.facebook_page_id,
        media_file_id=item.media_file_id, publish_mode=payload.publish_mode, status="success",
        ai_caption=caption, title=payload.title, description=payload.description, published_at=datetime.now(timezone.utc),
    )
    await queue_repo.set_queue_status(session, item.id, "published")
    return result


@router.get("/pipelines/{pipeline_id}/queue", response_model=list[QueueItemRead])
async def list_queue(pipeline_id: str, status: str | None = None, session: AsyncSession = Depends(get_session)):
    if await pipeline_repo.get_pipeline(session, pipeline_id) is None:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Pipeline not found"})
    rows = await queue_repo.list_queue(session, pipeline_id, status=status)
    return [_queue_read(q) for q in rows]


@router.get("/pipelines/{pipeline_id}/history", response_model=list[PublicationRead])
async def list_history(pipeline_id: str, limit: int = 50, offset: int = 0, session: AsyncSession = Depends(get_session)):
    if await pipeline_repo.get_pipeline(session, pipeline_id) is None:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Pipeline not found"})
    rows = await history_repo.list_publications(session, pipeline_id, limit=limit, offset=offset)
    return [_history_read(h) for h in rows]


@router.get("/pipelines/{pipeline_id}/schedules", response_model=list[ScheduleRead])
async def list_schedules(pipeline_id: str, date: str | None = None, session: AsyncSession = Depends(get_session)):
    if await pipeline_repo.get_pipeline(session, pipeline_id) is None:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Pipeline not found"})
    from ..services.scheduler import ensure_today_schedule
    pipeline = await pipeline_repo.get_pipeline(session, pipeline_id)
    await ensure_today_schedule(session, pipeline_id)
    result = await sched_repo.get_schedule_for_date(session, pipeline_id, date or _today_str(pipeline))
    return [_schedule_read(s) for s in result]


def _extract_video_id(url: str) -> str | None:
    import re
    m = re.search(r"(?:v=|\.be/|shorts/|v/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


def _today_str(pipeline) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(pipeline.timezone)).strftime("%Y-%m-%d")


def _page_read(p) -> dict:
    return {
        "id": p.id, "pipeline_id": p.pipeline_id, "page_id": p.page_id, "page_name": p.page_name,
        "scopes": p.scopes, "is_default": p.is_default, "status": p.status, "error": p.error,
        "synced_at": p.synced_at, "created_at": p.created_at,
    }


def _queue_read(q) -> dict:
    return {
        "id": q.id, "pipeline_id": q.pipeline_id, "youtube_video_id": q.youtube_video_id, "facebook_page_id": q.facebook_page_id,
        "media_file_id": q.media_file_id, "schedule_id": q.schedule_id, "status": q.status, "priority": q.priority,
        "scheduled_for": q.scheduled_for, "retry_count": q.retry_count, "publish_mode": q.publish_mode,
        "ai_caption": q.ai_caption, "ai_enhanced": q.ai_enhanced, "title": q.title, "description": q.description,
        "started_at": q.started_at, "completed_at": q.completed_at, "created_at": q.created_at,
    }


def _history_read(h) -> dict:
    return {
        "id": h.id, "pipeline_id": h.pipeline_id, "youtube_video_id": h.youtube_video_id, "facebook_page_id": h.facebook_page_id,
        "media_file_id": h.media_file_id, "facebook_post_id": h.facebook_post_id, "facebook_video_id": h.facebook_video_id,
        "facebook_reel_id": h.facebook_reel_id, "publish_mode": h.publish_mode, "status": h.status, "ai_caption": h.ai_caption,
        "ai_enhanced": h.ai_enhanced, "title": h.title, "description": h.description, "published_at": h.published_at, "created_at": h.created_at,
    }


def _schedule_read(s) -> dict:
    return {
        "id": s.id, "pipeline_id": s.pipeline_id, "scheduled_date": s.scheduled_date, "slot_index": s.slot_index,
        "slot_time": s.slot_time, "slot_max_daily": s.slot_max_daily, "publish_count": s.publish_count,
        "reserved_count": s.reserved_count, "is_active": s.is_active, "created_at": s.created_at,
    }
