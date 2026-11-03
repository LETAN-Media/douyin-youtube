from datetime import datetime, timedelta, timezone
from typing import Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.db.repositories import pipelines as pipeline_repo
from app.db.repositories import sources as sources_repo
from app.db.repositories import videos as videos_repo
from app.auth import require_admin
from app.dto import PipelineCreate, PipelineRead, PipelineUpdate, SourceCreate, SourceRead
from app.services.workers import run_scan_pipeline

router = APIRouter()


@router.get("/pipelines", response_model=list[PipelineRead])
async def list_pipelines(limit: int = Query(100, le=500), offset: int = 0, session: AsyncSession = Depends(get_session)):
    rows = await pipeline_repo.list_pipelines(session, limit=limit, offset=offset)
    out = []
    for p in rows:
        vc = await pipeline_repo.count_videos(session, p.id)
        out.append({
            "id": p.id, "name": p.name, "description": p.description, "status": p.status,
            "ordering": p.ordering, "max_daily_publish": p.max_daily_publish, "timezone": p.timezone,
            "publish_slots": p.publish_slots, "slot_window_minutes": p.slot_window_minutes,
            "slot_max_daily": p.slot_max_daily, "min_interval_minutes": p.min_interval_minutes,
            "auto_scan": p.auto_scan, "auto_publish": p.auto_publish, "next_scan_at": p.next_scan_at,
            "youtube_channel_id": p.youtube_channel_id, "youtube_channel_title": p.youtube_channel_title,
            "ai_strategy": p.ai_strategy, "ai_model": p.ai_model, "default_publish_mode": p.default_publish_mode,
            "default_facebook_page_id": p.default_facebook_page_id, "created_at": p.created_at, "updated_at": p.updated_at,
            "video_count": vc,
        })
    return out


@router.post("/pipelines", response_model=PipelineRead, status_code=status.HTTP_201_CREATED)
async def create_pipeline(payload: PipelineCreate, session: AsyncSession = Depends(get_session)):
    p = await pipeline_repo.create_pipeline(session, name=payload.name, description=payload.description, timezone=payload.timezone, ordering=payload.ordering, max_daily_publish=payload.max_daily_publish, publish_slots=payload.publish_slots or [], slot_max_daily=payload.slot_max_daily, min_interval_minutes=payload.min_interval_minutes, auto_scan=payload.auto_scan, auto_publish=payload.auto_publish, youtube_channel_id=payload.youtube_channel_id, ai_strategy=payload.ai_strategy, ai_model=payload.ai_model, default_publish_mode=payload.default_publish_mode, default_facebook_page_id=payload.default_facebook_page_id, settings=payload.settings)
    return _pipeline_read(p, 0)


@router.get("/pipelines/{pipeline_id}", response_model=PipelineRead)
async def get_pipeline(pipeline_id: str, session: AsyncSession = Depends(get_session)):
    p = await pipeline_repo.get_pipeline(session, pipeline_id)
    if p is None:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Pipeline not found"})
    vc = await pipeline_repo.count_videos(session, p.id)
    return _pipeline_read(p, vc)


@router.patch("/pipelines/{pipeline_id}", response_model=PipelineRead)
async def update_pipeline(pipeline_id: str, payload: PipelineUpdate, session: AsyncSession = Depends(get_session)):
    fields = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    p = await pipeline_repo.update_pipeline(session, pipeline_id, **fields)
    if p is None:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Pipeline not found"})
    vc = await pipeline_repo.count_videos(session, p.id)
    return _pipeline_read(p, vc)


@router.delete("/pipelines/{pipeline_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pipeline(pipeline_id: str, session: AsyncSession = Depends(get_session)):
    ok = await pipeline_repo.delete_pipeline(session, pipeline_id)
    if not ok:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Pipeline not found"})
    return None


@router.get("/pipelines/{pipeline_id}/sources", response_model=list[SourceRead])
async def list_sources(pipeline_id: str, session: AsyncSession = Depends(get_session)):
    if await pipeline_repo.get_pipeline(session, pipeline_id) is None:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Pipeline not found"})
    return await sources_repo.list_sources(session, pipeline_id)


@router.post("/pipelines/{pipeline_id}/sources", response_model=SourceRead)
async def create_source(pipeline_id: str, payload: SourceCreate, session: AsyncSession = Depends(get_session)):
    if await pipeline_repo.get_pipeline(session, pipeline_id) is None:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Pipeline not found"})
    src = await sources_repo.add_source(session, pipeline_id, source_type=payload.source_type, channel_id=payload.channel_id, channel_title=payload.channel_title, playlist_id=payload.playlist_id, custom_url=payload.custom_url)
    return src


@router.delete("/pipelines/{pipeline_id}/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(pipeline_id: str, source_id: str, session: AsyncSession = Depends(get_session)):
    ok = await sources_repo.delete_source(session, source_id)
    if not ok:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Source not found"})
    return None


@router.get("/pipelines/{pipeline_id}/videos", response_model=list)
async def list_videos(pipeline_id: str, limit: int = Query(50, le=200), offset: int = 0, session: AsyncSession = Depends(get_session)):
    if await pipeline_repo.get_pipeline(session, pipeline_id) is None:
        raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Pipeline not found"})
    rows = await videos_repo.list_videos(session, pipeline_id, limit=limit, offset=offset)
    return rows


def _pipeline_read(p, video_count: int) -> dict:
    return {
        "id": p.id, "name": p.name, "description": p.description, "status": p.status,
        "ordering": p.ordering, "max_daily_publish": p.max_daily_publish, "timezone": p.timezone,
        "publish_slots": p.publish_slots, "slot_window_minutes": p.slot_window_minutes,
        "slot_max_daily": p.slot_max_daily, "min_interval_minutes": p.min_interval_minutes,
        "auto_scan": p.auto_scan, "auto_publish": p.auto_publish, "next_scan_at": p.next_scan_at,
        "youtube_channel_id": p.youtube_channel_id, "youtube_channel_title": p.youtube_channel_title,
        "ai_strategy": p.ai_strategy, "ai_model": p.ai_model, "default_publish_mode": p.default_publish_mode,
        "default_facebook_page_id": p.default_facebook_page_id, "created_at": p.created_at, "updated_at": p.updated_at,
        "video_count": video_count,
    }
