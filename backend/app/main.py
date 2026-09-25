import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from typing import Any

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
)
from fastapi.middleware.cors import (
    CORSMiddleware,
)
from fastapi.responses import (
    HTMLResponse,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import (
    Base,
    engine,
    get_db,
)
from app.migrate import run_migrations
from app.models import (
    Destination,
    DouyinSource,
    DouyinVideo,
    Pipeline,
    Publication,
    VideoJob,
)
from app.schemas import (
    ChannelAddSourceRequest,
    ChannelAutoStatus,
    ChannelDetailResponse,
    ChannelItem,
    ChannelUpdateRequest,
    DestinationCreate,
    DestinationOut,
    DestinationUpdate,
    DouyinSourceCreate,
    DouyinQuotaOut,
    DouyinSourceOut,
    DouyinSourceUpdate,
    DouyinVideoOut,
    DouyinVideoWithPublications,
    InventoryListResponse,
    JobCreate,
    JobOut,
    ManualMetadataItem,
    ManualMetadataRequest,
    ManualMetadataResponse,
    ManualPublicationItem,
    ManualPublishRequest,
    ManualPublishResponse,
    ManualResolveRequest,
    ManualResolveResponse,
    PipelineCreate,
    PipelineOut,
    PipelineUpdate,
    PublicationOut,
    PublicationPublishRequest,
    PublicationRescheduleRequest,
    SourceCookieSave,
    SourceCookieStatus,
    SourceCookieTestResponse,
    SourceImportResponse,
    SourceInventoryResponse,
    SourceWithCookieOut,
    SourceSyncResponse,
)
from app.security import require_admin
from app.worker import (
    recover_incomplete_jobs,
    worker_loop,
)
from app.youtube import (
    complete_oauth,
    create_oauth_url,
    get_youtube_status,
)
from app.monitor import monitor_loop
from app.scheduler import scheduler_loop
from app.douyin_url import parse_douyin_profile_url
from app.ai_metadata import generate_metadata_structured
from app.douyin import call_rcuts_parser
import json
import re
import subprocess
import urllib.request


logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s "
        "%(levelname)s "
        "%(name)s "
        "%(message)s"
    ),
)

logger = logging.getLogger("douyin-youtube-api")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


worker_task: asyncio.Task | None = None
monitor_task: asyncio.Task | None = None
scheduler_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(
    app: FastAPI,
):
    global worker_task, monitor_task

    Base.metadata.create_all(
        bind=engine
    )

    run_migrations()

    recover_incomplete_jobs()

    if settings.worker_enabled:
        worker_task = (
            asyncio.create_task(
                worker_loop()
            )
        )

    if getattr(settings, "monitor_enabled", True):
        monitor_task = (
            asyncio.create_task(
                monitor_loop()
            )
        )
    else:
        monitor_task = None
        logger.info("Douyin monitor is disabled via MONITOR_ENABLED=false")

    if getattr(settings, "scheduler_enabled", True):
        scheduler_task = (
            asyncio.create_task(
                scheduler_loop()
            )
        )
    else:
        scheduler_task = None
        logger.info("Douyin scheduler is disabled via SCHEDULER_ENABLED=false")

    yield

    if worker_task:
        worker_task.cancel()

        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    if monitor_task is not None:
        monitor_task.cancel()

        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

    if scheduler_task is not None:
        scheduler_task.cancel()

        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
)


origins = settings.allowed_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": (
            "douyin-youtube"
        ),
        "worker": (
            settings.worker_enabled
        ),
        "monitor": (
            getattr(settings, "monitor_enabled", True)
            and monitor_task is not None
        ),
    }


@app.get(
    "/api/dashboard",
    dependencies=[
        Depends(require_admin)
    ],
)
def dashboard_stats(
    db: Session = Depends(
        get_db
    ),
) -> dict:
    pipelines = db.execute(
        select(Pipeline).order_by(Pipeline.created_at.asc())
    ).scalars().all()

    pipeline_ids = [p.id for p in pipelines]

    stats: dict[str, dict[str, Any]] = {}

    if pipeline_ids:
        job_stats = db.execute(
            select(
                VideoJob.pipeline_id,
                func.count(VideoJob.id).label("total"),
                func.sum(
                    __import__("sqlalchemy")
                    .case(
                        (VideoJob.status == "published", 1),
                        else_=0,
                    )
                ).label("published"),
                func.sum(
                    __import__("sqlalchemy")
                    .case(
                        (VideoJob.status == "pending", 1),
                        else_=0,
                    )
                ).label("pending"),
            )
            .where(VideoJob.pipeline_id.in_(pipeline_ids))
            .group_by(VideoJob.pipeline_id)
        ).all()

        for row in job_stats:
            stats[str(row.pipeline_id)] = {
                "total": int(row.total or 0),
                "published": int(row.published or 0),
                "pending": int(row.pending or 0),
            }

    source_counts: dict[str, int] = {}
    if pipeline_ids:
        source_rows = db.execute(
            select(
                DouyinSource.pipeline_id,
                func.count(DouyinSource.id).label("count"),
            )
            .where(DouyinSource.pipeline_id.in_(pipeline_ids))
            .group_by(DouyinSource.pipeline_id)
        ).all()

        for row in source_rows:
            source_counts[str(row.pipeline_id)] = int(row.count or 0)

    inventory_stats: dict[str, dict[str, Any]] = {}
    if pipeline_ids:
        inv_rows = db.execute(
            select(
                DouyinVideo.pipeline_id,
                func.count(DouyinVideo.id).label("inventory_total"),
                func.sum(
                    __import__("sqlalchemy")
                    .case(
                        (DouyinVideo.status == "backlog", 1),
                        else_=0,
                    )
                ).label("backlog"),
                func.sum(
                    __import__("sqlalchemy")
                    .case(
                        (DouyinVideo.status == "new", 1),
                        else_=0,
                    )
                ).label("new"),
                func.sum(
                    __import__("sqlalchemy")
                    .case(
                        (DouyinVideo.status == "scheduled", 1),
                        else_=0,
                    )
                ).label("scheduled"),
                func.sum(
                    __import__("sqlalchemy")
                    .case(
                        (DouyinVideo.status == "published", 1),
                        else_=0,
                    )
                ).label("published"),
            )
            .where(DouyinVideo.pipeline_id.in_(pipeline_ids))
            .group_by(DouyinVideo.pipeline_id)
        ).all()

        for row in inv_rows:
            inventory_stats[str(row.pipeline_id)] = {
                "inventory_total": int(row.inventory_total or 0),
                "backlog": int(row.backlog or 0),
                "new": int(row.new or 0),
                "scheduled": int(row.scheduled or 0),
                "published": int(row.published or 0),
            }

    destination_counts: dict[str, int] = {}
    if pipeline_ids:
        dest_rows = db.execute(
            select(
                Destination.pipeline_id,
                func.count(Destination.id).label("count"),
            )
            .where(Destination.pipeline_id.in_(pipeline_ids))
            .group_by(Destination.pipeline_id)
        ).all()

        for row in dest_rows:
            destination_counts[str(row.pipeline_id)] = int(row.count or 0)

    publication_stats: dict[str, dict[str, int]] = {}
    if pipeline_ids:
        for pid in pipeline_ids:
            pub_total = db.execute(
                select(func.count(Publication.id))
                .where(Publication.pipeline_id == pid)
            ).scalar_one_or_none() or 0
            pub_failed = db.execute(
                select(func.count(Publication.id))
                .where(Publication.pipeline_id == pid)
                .where(Publication.status == "failed")
            ).scalar_one_or_none() or 0
            pub_scheduled = db.execute(
                select(func.count(Publication.id))
                .where(Publication.pipeline_id == pid)
                .where(Publication.status.in_(["scheduled", "queued"]))
            ).scalar_one_or_none() or 0
            pub_published = db.execute(
                select(func.count(Publication.id))
                .where(Publication.pipeline_id == pid)
                .where(Publication.status == "published")
            ).scalar_one_or_none() or 0
            publication_stats[str(pid)] = {
                "total": int(pub_total),
                "failed": int(pub_failed),
                "scheduled": int(pub_scheduled),
                "published": int(pub_published),
            }

    result = []

    for pipeline in pipelines:
        pipeline_id = str(pipeline.id)
        job_stat = stats.get(pipeline_id, {"total": 0, "published": 0, "pending": 0})
        inv_stat = inventory_stats.get(pipeline_id, {
            "inventory_total": 0,
            "backlog": 0,
            "new": 0,
            "scheduled": 0,
            "published": 0,
        })
        pub_stat = publication_stats.get(pipeline_id, {
            "total": 0,
            "failed": 0,
            "scheduled": 0,
            "published": 0,
        })

        today_start = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_published = db.execute(
            select(func.count(VideoJob.id))
            .where(VideoJob.pipeline_id == pipeline.id)
            .where(VideoJob.status == "published")
            .where(VideoJob.created_at >= today_start)
        ).scalar_one_or_none()
        today_published = today_published or 0

        next_upload = None
        if pipeline.upload_slots:
            slot_times = []
            for slot_str in pipeline.upload_slots:
                try:
                    hour, minute = map(int, str(slot_str).split(":"))
                    slot_time = datetime.combine(_utcnow().date(), datetime.min.time().replace(hour=hour, minute=minute))
                    if slot_time.tzinfo is None:
                        slot_time = slot_time.replace(tzinfo=timezone.utc)
                    slot_times.append(slot_time)
                except (ValueError, AttributeError):
                    continue

            future_slots = [s for s in slot_times if s >= _utcnow()]
            if future_slots:
                next_upload = min(future_slots).isoformat()
            elif slot_times:
                tomorrow = _utcnow().date() + timedelta(days=1)
                try:
                    hour, minute = map(int, str(pipeline.upload_slots[0]).split(":"))
                    slot_time = datetime.combine(tomorrow, datetime.min.time().replace(hour=hour, minute=minute))
                    if slot_time.tzinfo is None:
                        slot_time = slot_time.replace(tzinfo=timezone.utc)
                    next_upload = slot_time.isoformat()
                except (ValueError, AttributeError):
                    next_upload = None

        pub_today = db.execute(
            select(func.count(Publication.id))
            .where(Publication.pipeline_id == pipeline.id)
            .where(Publication.status == "published")
            .where(Publication.published_at >= today_start)
        ).scalar_one_or_none() or 0

        # Inventory guard + auto reason for Overview observability.
        inv_available = int(inv_stat.get("new", 0) or 0) + int(
            inv_stat.get("backlog", 0) or 0
        )
        dests = list(
            db.execute(
                select(Destination)
                .where(Destination.pipeline_id == pipeline.id)
            ).scalars().all()
        )
        connected_dests = [
            d for d in dests
            if d.enabled and d.connected and d.credentials
            and (d.platform or "").lower() == "youtube"
        ]
        auto_reason: str | None = None
        if not pipeline.enabled:
            auto_reason = "SCHEDULER_DISABLED"
        elif not dests:
            auto_reason = "DESTINATION_NOT_CONNECTED"
        elif not connected_dests:
            auto_reason = "DESTINATION_NOT_CONNECTED"
        elif inv_available <= 0:
            auto_reason = "NO_AVAILABLE_INVENTORY"
        else:
            # Surface stored per-destination skip reason if any.
            reasons = [
                d.last_skip_reason for d in dests
                if d.last_skip_reason
            ]
            if reasons:
                # Prefer actionable reasons over waiting.
                for cand in (
                    "NO_AVAILABLE_INVENTORY",
                    "DESTINATION_NOT_CONNECTED",
                    "DAILY_LIMIT_REACHED",
                    "WORKER_ERROR",
                    "SCHEDULER_DISABLED",
                ):
                    if cand in reasons:
                        auto_reason = cand
                        break
                auto_reason = auto_reason or reasons[0]
            else:
                auto_reason = (
                    "WAITING_NEXT_SLOT"
                    if int(pub_today or 0) == 0 else None
                )

        result.append({
            "id": pipeline_id,
            "name": pipeline.name,
            "slug": pipeline.slug,
            "enabled": pipeline.enabled,
            "youtube_connected": pipeline.youtube_connected,
            "youtube_channel_title": pipeline.youtube_channel_title,
            "sources_count": source_counts.get(pipeline_id, 0),
            "destinations_count": destination_counts.get(pipeline_id, 0),
            "jobs_total": job_stat["total"],
            "jobs_published": job_stat["published"],
            "jobs_pending": job_stat["pending"],
            "default_privacy": pipeline.default_privacy,
            "inventory_total": inv_stat["inventory_total"],
            "backlog": inv_stat["backlog"],
            "new": inv_stat["new"],
            "scheduled": inv_stat["scheduled"],
            "published_inventory": inv_stat["published"],
            "today_published": today_published,
            "publications_total": pub_stat["total"],
            "publications_failed": pub_stat["failed"],
            "publications_scheduled": pub_stat["scheduled"],
            "publications_published": pub_stat["published"],
            "published_today": int(pub_today),
            "failed": int(pub_stat["failed"]),
            "daily_upload_limit": pipeline.daily_upload_limit,
            "next_upload": next_upload,
            "inventory_available": int(inv_available),
            "connected_destinations": len(connected_dests),
            "auto_reason": auto_reason,
        })

    return {
        "pipelines": result,
    }


@app.get("/", include_in_schema=False)
def dashboard_page() -> HTMLResponse:
    return HTMLResponse(
        """
        <!doctype html>
        <html>
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
          <title>Douyin YouTube Dashboard</title>
          <style>
            * { box-sizing: border-box; }
            body {
              font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
              background: #f5f5f5;
              margin: 0;
              padding: 20px;
            }
            .container {
              max-width: 1200px;
              margin: 0 auto;
            }
            h1 {
              color: #333;
              margin-bottom: 30px;
            }
            .grid {
              display: grid;
              grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
              gap: 20px;
            }
            .card {
              background: white;
              border-radius: 12px;
              padding: 24px;
              box-shadow: 0 2px 8px rgba(0,0,0,0.1);
              transition: transform 0.2s, box-shadow 0.2s;
            }
            .card:hover {
              transform: translateY(-2px);
              box-shadow: 0 4px 16px rgba(0,0,0,0.15);
            }
            .card-header {
              display: flex;
              justify-content: space-between;
              align-items: start;
              margin-bottom: 16px;
            }
            .pipeline-name {
              font-size: 18px;
              font-weight: 600;
              color: #111;
              margin: 0;
            }
            .status-badge {
              display: inline-block;
              padding: 4px 12px;
              border-radius: 20px;
              font-size: 12px;
              font-weight: 500;
              text-transform: uppercase;
            }
            .status-active {
              background: #d4f4dd;
              color: #1e7e34;
            }
            .status-inactive {
              background: #f8d7da;
              color: #721c24;
            }
            .card-body {
              space-y: 12px;
            }
            .stat-row {
              display: flex;
              justify-content: space-between;
              padding: 8px 0;
              border-bottom: 1px solid #f0f0f0;
            }
            .stat-row:last-child {
              border-bottom: none;
            }
            .stat-label {
              color: #666;
              font-size: 14px;
            }
            .stat-value {
              font-weight: 600;
              color: #333;
            }
            .youtube-status {
              display: flex;
              align-items: center;
              gap: 6px;
            }
            .dot {
              width: 8px;
              height: 8px;
              border-radius: 50%;
              display: inline-block;
            }
            .dot-connected {
              background: #28a745;
            }
            .dot-disconnected {
              background: #dc3545;
            }
            .create-card {
              border: 2px dashed #ccc;
              display: flex;
              align-items: center;
              justify-content: center;
              min-height: 200px;
              cursor: pointer;
              transition: all 0.2s;
            }
            .create-card:hover {
              border-color: #007bff;
              background: #f8f9fa;
            }
            .create-text {
              font-size: 16px;
              color: #666;
              font-weight: 500;
            }
            .loading {
              text-align: center;
              padding: 40px;
              color: #666;
            }
          </style>
        </head>
        <body>
          <div class="container">
            <h1>Pipelines</h1>
            <div id="app" class="loading">Loading...</div>
          </div>

          <script>
            async function loadDashboard() {
              try {
                const response = await fetch('/api/dashboard');
                const data = await response.json();

                const app = document.getElementById('app');

                if (!data.pipelines || data.pipelines.length === 0) {
                  app.innerHTML = '<div class="loading">No pipelines found. Create one to get started.</div>';
                  return;
                }

                let html = '<div class="grid">';

                for (const pipeline of data.pipelines) {
                  const statusClass = pipeline.enabled ? 'status-active' : 'status-inactive';
                  const statusText = pipeline.enabled ? 'Active' : 'Inactive';
                  const youtubeDot = pipeline.youtube_connected ? 'dot-connected' : 'dot-disconnected';
                  const youtubeText = pipeline.youtube_connected ? 'Connected' : 'Not Connected';
                  const youtubeTitle = pipeline.youtube_channel_title || 'Not Connected';

                  html += `
                    <div class="card">
                      <div class="card-header">
                        <h2 class="pipeline-name">${escapeHtml(pipeline.name)}</h2>
                        <span class="status-badge ${statusClass}">${statusText}</span>
                      </div>
                      <div class="card-body">
                        <div class="stat-row">
                          <span class="stat-label">YouTube</span>
                          <span class="stat-value youtube-status">
                            <span class="dot ${youtubeDot}"></span>
                            ${escapeHtml(youtubeTitle)}
                          </span>
                        </div>
                        <div class="stat-row">
                          <span class="stat-label">Douyin Sources</span>
                          <span class="stat-value">${pipeline.sources_count}</span>
                        </div>
                        <div class="stat-row">
                          <span class="stat-label">Published</span>
                          <span class="stat-value">${pipeline.jobs_published}</span>
                        </div>
                        <div class="stat-row">
                          <span class="stat-label">Pending</span>
                          <span class="stat-value">${pipeline.jobs_pending}</span>
                        </div>
                        <div class="stat-row">
                          <span class="stat-label">Total Jobs</span>
                          <span class="stat-value">${pipeline.jobs_total}</span>
                        </div>
                      </div>
                    </div>
                  `;
                }

                html += `
                  <div class="card create-card" onclick="alert('Create Pipeline API: POST /api/pipelines')">
                    <div class="create-text">+ Create Pipeline</div>
                  </div>
                `;

                html += '</div>';
                app.innerHTML = html;

              } catch (error) {
                document.getElementById('app').innerHTML = `
                  <div class="loading">
                    Failed to load dashboard: ${error.message}
                    <br><br>
                    <a href="/health">Check Health</a>
                  </div>
                `;
              }
            }

            function escapeHtml(text) {
              const div = document.createElement('div');
              div.textContent = text;
              return div.innerHTML;
            }

            loadDashboard();
            setInterval(loadDashboard, 30000);
          </script>
        </body>
        </html>
        """
    )


@app.post(
    "/api/jobs",
    response_model=JobOut,
    dependencies=[
        Depends(require_admin)
    ],
)
def create_job(
    payload: JobCreate,
    db: Session = Depends(
        get_db
    ),
) -> VideoJob:
    pipeline_id = payload.pipeline_id
    if not pipeline_id:
        pipeline = db.execute(
            select(Pipeline)
            .where(Pipeline.slug == "vibe-men-world")
            .limit(1)
        ).scalar_one_or_none()

        if not pipeline:
            raise HTTPException(
                status_code=400,
                detail="Không tìm thấy default pipeline",
            )

        pipeline_id = pipeline.id

    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(
            status_code=400,
            detail="Pipeline không tồn tại",
        )

    if not pipeline.enabled:
        raise HTTPException(
            status_code=400,
            detail="Pipeline đang bị disabled",
        )

    privacy_status = payload.privacy_status or pipeline.default_privacy

    initial_description = payload.description
    if not initial_description and payload.share_text:
        initial_description = payload.share_text

    job = VideoJob(
        source_url=(
            payload.douyin_url
        ),
        title=payload.title,
        description=initial_description,
        privacy_status=privacy_status,
        status="pending",
        pipeline_id=pipeline_id,
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    return job


@app.get(
    "/api/jobs",
    response_model=list[JobOut],
    dependencies=[
        Depends(require_admin)
    ],
)
def list_jobs(
    db: Session = Depends(
        get_db
    ),
) -> list[VideoJob]:
    statement = (
        select(VideoJob)
        .order_by(
            VideoJob.created_at.desc()
        )
        .limit(100)
    )

    return list(
        db.execute(statement)
        .scalars()
        .all()
    )


@app.get(
    "/api/jobs/{job_id}",
    response_model=JobOut,
    dependencies=[
        Depends(require_admin)
    ],
)
def get_job(
    job_id: str,
    db: Session = Depends(
        get_db
    ),
) -> VideoJob:
    job = db.get(
        VideoJob,
        job_id,
    )

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy job",
        )

    return job


@app.post(
    "/api/jobs/{job_id}/retry",
    response_model=JobOut,
    dependencies=[
        Depends(require_admin)
    ],
)
def retry_job(
    job_id: str,
    db: Session = Depends(
        get_db
    ),
) -> VideoJob:
    job = db.get(
        VideoJob,
        job_id,
    )

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy job",
        )

    if job.status not in {
        "failed",
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "Chỉ retry job "
                "đang failed"
            ),
        )

    job.status = "pending"
    job.error = None
    job.progress = 0

    db.commit()
    db.refresh(job)

    return job


@app.get(
    "/api/pipelines",
    response_model=list[PipelineOut],
    dependencies=[
        Depends(require_admin)
    ],
)
def list_pipelines(
    db: Session = Depends(
        get_db
    ),
) -> list[Pipeline]:
    statement = (
        select(Pipeline)
        .order_by(Pipeline.created_at.asc())
        .limit(100)
    )

    return list(
        db.execute(statement)
        .scalars()
        .all()
    )


@app.post(
    "/api/pipelines",
    response_model=PipelineOut,
    status_code=201,
    dependencies=[
        Depends(require_admin)
    ],
)
def create_pipeline(
    payload: PipelineCreate,
    db: Session = Depends(
        get_db
    ),
) -> Pipeline:
    pipeline = Pipeline(
        name=payload.name,
        slug=payload.slug,
        niche=payload.niche,
        language=payload.language,
        fixed_hashtags=payload.fixed_hashtags,
        adaptive_hashtags=payload.adaptive_hashtags,
        prompt_profile=payload.prompt_profile,
        default_privacy=payload.default_privacy,
        enabled=payload.enabled,
    )

    db.add(pipeline)
    db.commit()
    db.refresh(pipeline)

    return pipeline


@app.get(
    "/api/pipelines/{pipeline_id}",
    response_model=PipelineOut,
    dependencies=[
        Depends(require_admin)
    ],
)
def get_pipeline(
    pipeline_id: str,
    db: Session = Depends(
        get_db
    ),
) -> Pipeline:
    pipeline = db.get(
        Pipeline,
        pipeline_id,
    )

    if pipeline is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy pipeline",
        )

    return pipeline


@app.patch(
    "/api/pipelines/{pipeline_id}",
    response_model=PipelineOut,
    dependencies=[
        Depends(require_admin)
    ],
)
def update_pipeline(
    pipeline_id: str,
    payload: PipelineUpdate,
    db: Session = Depends(
        get_db
    ),
) -> Pipeline:
    pipeline = db.get(
        Pipeline,
        pipeline_id,
    )

    if pipeline is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy pipeline",
        )

    update_data = payload.model_dump(
        exclude_none=True,
    )

    for key, value in update_data.items():
        setattr(pipeline, key, value)

    db.commit()
    db.refresh(pipeline)

    return pipeline


@app.get(
    "/api/pipelines/{pipeline_id}/sources",
    dependencies=[
        Depends(require_admin)
    ],
)
def list_pipeline_sources(
    pipeline_id: str,
    db: Session = Depends(
        get_db
    ),
) -> list[dict]:
    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy pipeline",
        )

    # Return both legacy DouyinSource and new PipelineSource (generic)
    from app.models import PipelineSource

    douyin = list(
        db.execute(
            select(DouyinSource)
            .where(DouyinSource.pipeline_id == pipeline_id)
            .order_by(DouyinSource.created_at.asc())
        )
        .scalars()
        .all()
    )
    generic = list(
        db.execute(
            select(PipelineSource)
            .where(PipelineSource.pipeline_id == pipeline_id)
            .order_by(PipelineSource.created_at.asc())
        )
        .scalars()
        .all()
    )
    out: list[dict] = []
    for s in douyin:
        out.append(
            {
                "id": s.id,
                "pipeline_id": s.pipeline_id,
                "platform": getattr(s, "platform", "douyin") or "douyin",
                "source_external_id": getattr(s, "douyin_sec_uid", None),
                "source_url": getattr(s, "profile_url", None),
                "source_name": s.name,
                "enabled": s.enabled,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
        )
    for g in generic:
        out.append(
            {
                "id": g.id,
                "pipeline_id": g.pipeline_id,
                "platform": g.platform,
                "source_external_id": g.source_external_id,
                "source_url": g.source_url,
                "source_name": g.source_name,
                "enabled": g.enabled,
                "created_at": g.created_at.isoformat() if g.created_at else None,
            }
        )
    return out


@app.post(
    "/api/pipelines/{pipeline_id}/sources",
    status_code=201,
    dependencies=[
        Depends(require_admin)
    ],
)
def create_pipeline_source(
    pipeline_id: str,
    payload: dict,
    db: Session = Depends(
        get_db
    ),
):
    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy pipeline",
        )

    # Generic platform handling (douyin/facebook). Douyin uses DouyinSource table for
    # backwards compat with inventory; Facebook uses PipelineSource.
    platform = (payload.get("platform") or "douyin").lower() if isinstance(payload, dict) else getattr(payload, "platform", "douyin") or "douyin"
    # Normalize payload to dict for generic handling
    if isinstance(payload, dict):
        p_name = (payload.get("name") or payload.get("source_name") or "").strip()
        p_profile_url = payload.get("profile_url") or payload.get("source_url") or payload.get("url") or ""
        p_sec_uid = payload.get("douyin_sec_uid") or payload.get("source_external_id") or ""
        p_user_id = payload.get("douyin_user_id") or ""
        p_enabled = payload.get("enabled", True)
    else:
        p_name = payload.name
        p_profile_url = payload.profile_url
        p_sec_uid = payload.douyin_sec_uid
        p_user_id = payload.douyin_user_id
        p_enabled = payload.enabled
    if not p_name:
        p_name = f"{platform.capitalize()} Creator"
    if platform == "facebook":
        from app.models import PipelineSource as _PS
        from app.source_providers import registry as _reg
        prov = _reg.get("facebook")
        resolved = prov.resolve_source(p_profile_url) if prov else {"source_external_id": p_profile_url, "source_url": p_profile_url}
        ps = _PS(
            pipeline_id=pipeline_id,
            platform="facebook",
            source_external_id=resolved.get("source_external_id") or p_profile_url,
            source_url=resolved.get("source_url") or p_profile_url,
            source_name=p_name,
            enabled=bool(p_enabled),
        )
        db.add(ps)
        db.commit()
        db.refresh(ps)
        return ps  # type: ignore

    profile_url = p_profile_url
    douyin_sec_uid = p_sec_uid
    original_profile_url = profile_url

    if profile_url and not douyin_sec_uid:
        parsed = parse_douyin_profile_url(profile_url)
        if parsed:
            douyin_sec_uid = parsed.sec_uid
            profile_url = parsed.canonical

    source = DouyinSource(
        pipeline_id=pipeline_id,
        name=p_name,
        original_profile_url=original_profile_url,
        profile_url=profile_url,
        douyin_sec_uid=douyin_sec_uid or p_sec_uid,
        douyin_user_id=p_user_id,
        enabled=bool(p_enabled),
        platform="douyin",
        inventory_sync_status="idle",
        inventory_count=0,
        inventory_sync_error=None,
        feed_provider=getattr(settings, "douyin_creator_provider", "rapidapi_justone") or "rapidapi_justone",
        initial_import_status="pending",
    )

    db.add(source)
    db.commit()
    db.refresh(source)

    # Manual-inventory mode: creating a source does NOT spend a RapidAPI
    # request. The admin starts the one-off import from the dashboard
    # (POST /api/sources/{id}/initial-import).
    return source


@app.get(
    "/api/sources/{source_id}",
    response_model=DouyinSourceOut,
    dependencies=[
        Depends(require_admin)
    ],
)
def get_source(
    source_id: str,
    db: Session = Depends(
        get_db
    ),
) -> DouyinSource:
    source = db.get(DouyinSource, source_id)

    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy source",
        )

    return source


@app.patch(
    "/api/sources/{source_id}",
    response_model=DouyinSourceOut,
    dependencies=[
        Depends(require_admin)
    ],
)
def update_source(
    source_id: str,
    payload: DouyinSourceUpdate,
    db: Session = Depends(
        get_db
    ),
) -> DouyinSource:
    source = db.get(DouyinSource, source_id)

    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy source",
        )

    update_data = payload.model_dump(
        exclude_none=True,
    )

    for key, value in update_data.items():
        setattr(source, key, value)

    db.commit()
    db.refresh(source)

    return source


@app.delete(
    "/api/sources/{source_id}",
    status_code=204,
    dependencies=[
        Depends(require_admin)
    ],
)
def delete_source(
    source_id: str,
    db: Session = Depends(
        get_db
    ),
) -> None:
    source = db.get(DouyinSource, source_id)

    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy source",
        )

    db.delete(source)
    db.commit()


@app.get(
    "/api/destinations",
    response_model=list[DestinationOut],
    dependencies=[
        Depends(require_admin)
    ],
)
def list_all_destinations(
    db: Session = Depends(
        get_db
    ),
) -> list[Destination]:
    return list(
        db.execute(
            select(Destination).order_by(Destination.created_at.asc())
        )
        .scalars()
        .all()
    )


@app.get(
    "/api/pipelines/{pipeline_id}/destinations",
    response_model=list[DestinationOut],
    dependencies=[
        Depends(require_admin)
    ],
)
def list_pipeline_destinations(
    pipeline_id: str,
    db: Session = Depends(
        get_db
    ),
) -> list[Destination]:
    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy pipeline",
        )

    return list(
        db.execute(
            select(Destination)
            .where(Destination.pipeline_id == pipeline_id)
            .order_by(Destination.created_at.asc())
        )
        .scalars()
        .all()
    )


@app.post(
    "/api/pipelines/{pipeline_id}/destinations",
    response_model=DestinationOut,
    status_code=201,
    dependencies=[
        Depends(require_admin)
    ],
)
def create_pipeline_destination(
    pipeline_id: str,
    payload: DestinationCreate,
    db: Session = Depends(
        get_db
    ),
) -> Destination:
    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy pipeline",
        )

    destination = Destination(
        pipeline_id=pipeline_id,
        platform=payload.platform,
        name=payload.name,
        external_account_id=payload.external_account_id,
        external_account_name=payload.external_account_name,
        enabled=payload.enabled,
        daily_upload_limit=payload.daily_upload_limit,
        timezone=payload.timezone,
        upload_slots=payload.upload_slots,
        publish_strategy=payload.publish_strategy,
        metadata_language=payload.metadata_language,
        metadata_profile=payload.metadata_profile,
        fixed_hashtags=payload.fixed_hashtags,
        adaptive_hashtags=payload.adaptive_hashtags,
        prompt_override=payload.prompt_override,
    )

    db.add(destination)
    db.commit()
    db.refresh(destination)

    return destination


@app.get(
    "/api/destinations/{destination_id}",
    response_model=DestinationOut,
    dependencies=[
        Depends(require_admin)
    ],
)
def get_destination(
    destination_id: str,
    db: Session = Depends(
        get_db
    ),
) -> Destination:
    destination = db.get(Destination, destination_id)

    if destination is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy destination",
        )

    return destination


@app.patch(
    "/api/destinations/{destination_id}",
    response_model=DestinationOut,
    dependencies=[
        Depends(require_admin)
    ],
)
def update_destination(
    destination_id: str,
    payload: DestinationUpdate,
    db: Session = Depends(
        get_db
    ),
) -> Destination:
    destination = db.get(Destination, destination_id)

    if destination is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy destination",
        )

    update_data = payload.model_dump(
        exclude_none=True,
    )

    for key, value in update_data.items():
        setattr(destination, key, value)

    db.commit()
    db.refresh(destination)

    return destination


@app.delete(
    "/api/destinations/{destination_id}",
    status_code=204,
    dependencies=[
        Depends(require_admin)
    ],
)
def delete_destination(
    destination_id: str,
    db: Session = Depends(
        get_db
    ),
) -> None:
    destination = db.get(Destination, destination_id)

    if destination is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy destination",
        )

    db.delete(destination)
    db.commit()


@app.get(
    "/api/publications",
    response_model=list[PublicationOut],
    dependencies=[
        Depends(require_admin)
    ],
)
def list_publications(
    pipeline_id: str | None = Query(
        default=None,
    ),
    destination_id: str | None = Query(
        default=None,
    ),
    status: str | None = Query(
        default=None,
    ),
    limit: int = Query(
        default=200,
        ge=1,
        le=500,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    db: Session = Depends(
        get_db
    ),
) -> list[Publication]:
    query = select(Publication)

    if pipeline_id:
        query = query.where(Publication.pipeline_id == pipeline_id)

    if destination_id:
        query = query.where(Publication.destination_id == destination_id)

    if status:
        query = query.where(Publication.status == status)

    return list(
        db.execute(
            query.order_by(Publication.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )


def _destination_next_upload(destination: Destination) -> str | None:
    """Compute next upload slot without any DB access (pure)."""
    try:
        slots = destination.upload_slots or []
        if not slots:
            return None
        slot_times = []
        for slot_str in slots:
            try:
                hour, minute = map(int, str(slot_str).split(":"))
                slot_time = datetime.combine(
                    datetime.now().date(),
                    datetime.min.time().replace(hour=hour, minute=minute),
                )
                if slot_time.tzinfo is None:
                    slot_time = slot_time.replace(tzinfo=timezone.utc)
                slot_times.append(slot_time)
            except (ValueError, AttributeError):
                continue
        future_slots = [s for s in slot_times if s >= datetime.now(timezone.utc)]
        if future_slots:
            return min(future_slots).isoformat()
        if slot_times:
            tomorrow = datetime.now().date() + timedelta(days=1)
            hour, minute = map(int, str(slots[0]).split(":"))
            slot_time = datetime.combine(
                tomorrow,
                datetime.min.time().replace(hour=hour, minute=minute),
            )
            if slot_time.tzinfo is None:
                slot_time = slot_time.replace(tzinfo=timezone.utc)
            return slot_time.isoformat()
    except Exception:
        return None
    return None


@app.get(
    "/api/destinations/{destination_id}/status",
    dependencies=[
        Depends(require_admin)
    ],
)
def destination_status(
    destination_id: str,
    db: Session = Depends(
        get_db
    ),
) -> dict:
    destination = db.get(Destination, destination_id)

    if destination is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy destination",
        )

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    today_published = db.execute(
        select(func.count(Publication.id))
        .where(Publication.destination_id == destination_id)
        .where(Publication.status == "published")
        .where(Publication.published_at >= today_start)
    ).scalar_one_or_none()
    today_published = today_published or 0

    return {
        "connected": destination.connected,
        "platform": destination.platform,
        "name": destination.name,
        "daily_upload_limit": destination.daily_upload_limit,
        "today_published": today_published,
        "next_upload": _destination_next_upload(destination),
        "enabled": destination.enabled,
    }


@app.get(
    "/api/pipelines/{pipeline_id}/destinations/statuses",
    dependencies=[
        Depends(require_admin)
    ],
)
def pipeline_destination_statuses(
    pipeline_id: str,
    db: Session = Depends(
        get_db
    ),
) -> list[dict]:
    """Batch destination statuses: 1 request instead of N per-destination calls.

    Single grouped COUNT query + pure next-slot computation.
    """
    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy pipeline",
        )
    destinations = list(
        db.execute(
            select(Destination)
            .where(Destination.pipeline_id == pipeline_id)
            .order_by(Destination.created_at.asc())
        )
        .scalars()
        .all()
    )
    if not destinations:
        return []
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    dest_ids = [d.id for d in destinations]
    rows = db.execute(
        select(
            Publication.destination_id,
            func.count(Publication.id).label("cnt"),
        )
        .where(Publication.destination_id.in_(dest_ids))
        .where(Publication.status == "published")
        .where(Publication.published_at >= today_start)
        .group_by(Publication.destination_id)
    ).all()
    counts = {str(r[0]): int(r[1] or 0) for r in rows}
    return [
        {
            "destination_id": d.id,
            "connected": d.connected,
            "platform": d.platform,
            "name": d.name,
            "daily_upload_limit": d.daily_upload_limit,
            "today_published": counts.get(str(d.id), 0),
            "next_upload": _destination_next_upload(d),
            "enabled": d.enabled,
        }
        for d in destinations
    ]


@app.get(
    "/api/pipelines/{pipeline_id}/flow-state",
    dependencies=[
        Depends(require_admin)
    ],
)
def pipeline_flow_state(
    pipeline_id: str,
    db: Session = Depends(
        get_db
    ),
) -> dict:
    """Single endpoint for the realtime pipeline flow graph.

    Returns nodes (sources / processors / destinations) + active routes
    derived from REAL rows only: active VideoJobs (pending/downloading/
    uploading), queued+scheduled Publications, and failures from the last
    10 minutes. No N+1: fixed ~10 queries regardless of node counts.
    Frontend polls this every few seconds; never revalidates the page.
    """
    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy pipeline",
        )

    sources = list(
        db.execute(
            select(DouyinSource)
            .where(DouyinSource.pipeline_id == pipeline_id)
            .order_by(DouyinSource.created_at.asc())
        )
        .scalars()
        .all()
    )
    destinations = list(
        db.execute(
            select(Destination)
            .where(Destination.pipeline_id == pipeline_id)
            .order_by(Destination.created_at.asc())
        )
        .scalars()
        .all()
    )
    source_by_id = {s.id: s for s in sources}
    dest_by_id = {d.id: d for d in destinations}

    inventory_total = db.execute(
        select(func.count(DouyinVideo.id))
        .where(DouyinVideo.pipeline_id == pipeline_id)
    ).scalar_one_or_none() or 0

    pub_count_rows = db.execute(
        select(Publication.status, func.count(Publication.id))
        .where(Publication.pipeline_id == pipeline_id)
        .group_by(Publication.status)
    ).all()
    pub_counts = {str(r[0]): int(r[1] or 0) for r in pub_count_rows}

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    today_rows = db.execute(
        select(
            Publication.destination_id,
            func.count(Publication.id).label("cnt"),
        )
        .where(Publication.pipeline_id == pipeline_id)
        .where(Publication.status == "published")
        .where(Publication.published_at >= today_start)
        .group_by(Publication.destination_id)
    ).all()
    today_by_dest = {str(r[0]): int(r[1] or 0) for r in today_rows}

    last_pub_rows = db.execute(
        select(
            Publication.destination_id,
            func.max(Publication.published_at).label("last"),
        )
        .where(Publication.pipeline_id == pipeline_id)
        .where(Publication.status == "published")
        .group_by(Publication.destination_id)
    ).all()
    last_pub_by_dest = {
        str(r[0]): r[1].isoformat() if r[1] is not None else None
        for r in last_pub_rows
    }

    # Active publications (queued/scheduled) joined with their video.
    active_pub_rows = list(
        db.execute(
            select(Publication, DouyinVideo)
            .join(DouyinVideo, DouyinVideo.id == Publication.douyin_video_id)
            .where(Publication.pipeline_id == pipeline_id)
            .where(Publication.status.in_(["queued", "scheduled"]))
            .order_by(Publication.scheduled_at.asc())
            .limit(60)
        ).all()
    )

    # Recent failures (last 10 minutes) so failed paths render red.
    failed_since = datetime.now(timezone.utc) - timedelta(minutes=10)
    failed_pub_rows = list(
        db.execute(
            select(Publication, DouyinVideo)
            .join(DouyinVideo, DouyinVideo.id == Publication.douyin_video_id)
            .where(Publication.pipeline_id == pipeline_id)
            .where(Publication.status == "failed")
            .where(Publication.updated_at >= failed_since)
            .order_by(Publication.updated_at.desc())
            .limit(10)
        ).all()
    )

    # Active worker jobs carry the fine-grained stage + progress.
    active_jobs = list(
        db.execute(
            select(VideoJob)
            .where(VideoJob.pipeline_id == pipeline_id)
            .where(VideoJob.status.in_(["pending", "downloading", "uploading"]))
            .order_by(VideoJob.updated_at.desc())
            .limit(100)
        )
        .scalars()
        .all()
    )
    job_video_ids = list({j.source_video_id for j in active_jobs if j.source_video_id})
    job_videos: dict[str, DouyinVideo] = {}
    if job_video_ids:
        for v in db.execute(
            select(DouyinVideo)
            .where(DouyinVideo.pipeline_id == pipeline_id)
            .where(DouyinVideo.video_id.in_(job_video_ids))
        ).scalars().all():
            job_videos[str(v.video_id)] = v

    # Overlay jobs onto their publication route (unique per video+dest).
    jobs_by_route: dict[tuple[str, str], VideoJob] = {}
    for job in active_jobs:
        v = job_videos.get(str(job.source_video_id or ""))
        if v is None or not job.destination_id:
            continue
        jobs_by_route[(str(v.id), str(job.destination_id))] = job

    def _iso(dt: Any) -> str | None:
        try:
            return dt.isoformat() if dt is not None else None
        except Exception:
            return None

    routes: list[dict] = []
    seen_routes: set[tuple[str, str]] = set()

    def _route_from_pub(
        pub: Publication, video: DouyinVideo, failed: bool = False
    ) -> dict | None:
        source = source_by_id.get(str(video.source_id))
        dest = dest_by_id.get(str(pub.destination_id))
        if dest is None:
            return None
        job = jobs_by_route.get((str(video.id), str(pub.destination_id)))
        stage = str(job.status) if job is not None else str(pub.status)
        progress = int(job.progress) if job is not None and job.progress else None
        started = pub.started_at or pub.scheduled_at or pub.created_at
        return {
            "key": f"pub:{pub.id}",
            "publication_id": pub.id,
            "job_id": job.id if job is not None else None,
            "video_id": video.id,
            "video_title": video.title or video.video_id,
            "source_id": str(video.source_id),
            "source_name": source.name if source is not None else "—",
            "destination_id": str(pub.destination_id),
            "destination_name": dest.name,
            "platform": dest.platform,
            "stage": stage,
            "progress": progress,
            "attempts": int(pub.attempts or 0),
            "started_at": _iso(started),
            "scheduled_at": _iso(pub.scheduled_at),
            "error": (pub.error or (job.error if job is not None else None) or None)
            if failed
            else None,
            "failed": failed,
            "mode": str(getattr(pub, "publication_mode", "auto") or "auto"),
        }

    for pub, video in active_pub_rows:
        r = _route_from_pub(pub, video)
        if r is None:
            continue
        seen_routes.add((str(video.id), str(pub.destination_id)))
        routes.append(r)

    for pub, video in failed_pub_rows:
        r = _route_from_pub(pub, video, failed=True)
        if r is None:
            continue
        seen_routes.add((str(video.id), str(pub.destination_id)))
        routes.append(r)

    # Jobs without a matching publication row (should be rare).
    for job in active_jobs:
        v = job_videos.get(str(job.source_video_id or ""))
        if v is None or not job.destination_id:
            continue
        if (str(v.id), str(job.destination_id)) in seen_routes:
            continue
        dest = dest_by_id.get(str(job.destination_id))
        if dest is None:
            continue
        source = source_by_id.get(str(v.source_id))
        routes.append({
            "key": f"job:{job.id}",
            "publication_id": None,
            "job_id": job.id,
            "video_id": v.id,
            "video_title": v.title or v.video_id,
            "source_id": str(v.source_id),
            "source_name": source.name if source is not None else "—",
            "destination_id": str(job.destination_id),
            "destination_name": dest.name,
            "platform": dest.platform,
            "stage": str(job.status),
            "progress": int(job.progress) if job.progress else None,
            "attempts": int(job.attempts or 0),
            "started_at": _iso(job.updated_at or job.created_at),
            "scheduled_at": None,
            "error": job.error,
            "failed": False,
            "mode": "auto",
        })

    # Sort: failed first, then by stage order, then oldest started.
    stage_order = {
        "failed": 0, "downloading": 1, "uploading": 2, "pending": 3,
        "queued": 4, "scheduled": 5,
    }
    routes.sort(
        key=lambda r: (stage_order.get(str(r["stage"]), 9), str(r["started_at"] or ""))
    )

    syncing = sum(
        1 for s in sources
        if str(s.inventory_sync_status or "") in ("queued", "running")
    )
    sync_failed = sum(
        1 for s in sources
        if str(s.inventory_sync_status or "") in ("failed", "auth_required")
    )
    queued_n = sum(1 for r in routes if not r["failed"] and r["stage"] in ("queued", "scheduled"))
    active_n = sum(1 for r in routes if not r["failed"] and r["stage"] in ("pending", "downloading", "uploading"))
    failed_n = sum(1 for r in routes if r["failed"])

    if syncing > 0:
        inv_state, inv_detail = "syncing", f"{syncing} source đang quét"
    elif sync_failed > 0:
        inv_state, inv_detail = "error", f"{sync_failed} source lỗi sync"
    else:
        inv_state, inv_detail = "idle", f"{int(inventory_total)} videos"
    if active_n > 0:
        ai_state, ai_detail = "processing", f"{active_n} video đang xử lý"
    elif queued_n > 0:
        ai_state, ai_detail = "waiting", f"{queued_n} video chờ"
    else:
        ai_state, ai_detail = "idle", "Sẵn sàng"
    if any(not r["failed"] and r["stage"] == "scheduled" for r in routes):
        sch_state, sch_detail = "processing", "Đang lên lịch"
    elif pub_counts.get("scheduled", 0) + pub_counts.get("queued", 0) > 0:
        sch_state, sch_detail = (
            "waiting",
            f"{pub_counts.get('queued', 0) + pub_counts.get('scheduled', 0)} chờ lịch",
        )
    else:
        sch_state, sch_detail = "idle", "Trống"
    if any(not r["failed"] and r["stage"] == "uploading" for r in routes):
        pub_state, pub_detail = "processing", "Đang upload"
    elif failed_n > 0:
        pub_state, pub_detail = "error", f"{failed_n} lỗi gần đây"
    elif queued_n > 0:
        pub_state, pub_detail = "waiting", f"{queued_n} chờ upload"
    else:
        pub_state, pub_detail = "idle", "Sẵn sàng"

    def _username(s: DouyinSource) -> str | None:
        if s.douyin_user_id:
            return f"@{s.douyin_user_id}"
        if s.douyin_sec_uid:
            return f"@{s.douyin_sec_uid[:16]}…"
        return None

    return {
        "pipeline_id": pipeline_id,
        "summary": {
            "sources": len(sources),
            "inventory_total": int(inventory_total),
            "queue": int(pub_counts.get("queued", 0) + pub_counts.get("scheduled", 0)),
            "publishing": int(active_n),
            "failed": int(pub_counts.get("failed", 0)),
        },
        "sources": [
            {
                "id": s.id,
                "name": s.name,
                "username": _username(s),
                "inventory_count": int(s.inventory_count or 0),
                "sync_status": str(s.inventory_sync_status or "idle"),
                "enabled": bool(s.enabled),
            }
            for s in sources
        ],
        "processors": [
            {"key": "inventory", "label": "Inventory", "sub": "Thu thập Douyin", "state": inv_state, "detail": inv_detail},
            {"key": "ai", "label": "AI Metadata", "sub": "Title · Hashtags", "state": ai_state, "detail": ai_detail},
            {"key": "scheduler", "label": "Scheduler", "sub": "Upload slots", "state": sch_state, "detail": sch_detail},
            {"key": "publisher", "label": "Publisher", "sub": "Upload worker", "state": pub_state, "detail": pub_detail},
        ],
        "destinations": [
            {
                "id": d.id,
                "platform": d.platform,
                "name": d.name,
                "connected": bool(d.connected),
                "enabled": bool(d.enabled),
                "today_published": int(today_by_dest.get(str(d.id), 0)),
                "daily_upload_limit": int(d.daily_upload_limit or 0),
                "next_upload": _destination_next_upload(d),
                "last_published_at": last_pub_by_dest.get(str(d.id)),
            }
            for d in destinations
        ],
        "active_routes": routes,
    }


@app.get(
    "/api/youtube/status",
    dependencies=[
        Depends(require_admin)
    ],
)
def youtube_status(
    destination_id: str | None = Query(
        default=None,
    ),
    pipeline_id: str | None = Query(
        default=None,
    ),
    db: Session = Depends(
        get_db
    ),
) -> dict:
    if destination_id:
        destination = db.get(Destination, destination_id)
        if destination is None:
            raise HTTPException(
                status_code=404,
                detail="Không tìm thấy destination",
            )

        return {
            "connected": destination.connected,
            "destination_id": destination.id,
            "pipeline_id": destination.pipeline_id,
            "platform": destination.platform,
            "name": destination.name,
            "callback_url": settings.youtube_callback_url,
        }

    status = get_youtube_status(
        db,
        pipeline_id=pipeline_id,
    )
    status["callback_url"] = (
        settings.youtube_callback_url
    )
    return status


@app.post(
    "/api/youtube/oauth-url",
    dependencies=[
        Depends(require_admin)
    ],
)
def youtube_oauth_url(
    destination_id: str | None = Query(
        default=None,
    ),
    pipeline_id: str | None = Query(
        default=None,
    ),
    db: Session = Depends(
        get_db
    ),
) -> dict:
    resolved_destination_id = destination_id

    if not resolved_destination_id and pipeline_id:
        destination = db.execute(
            select(Destination)
            .where(Destination.pipeline_id == pipeline_id)
            .where(Destination.platform == "youtube")
            .limit(1)
        ).scalar_one_or_none()

        if destination:
            resolved_destination_id = destination.id

    try:
        url = create_oauth_url(
            db=db,
            pipeline_id=pipeline_id,
            destination_id=resolved_destination_id,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return {
        "url": url,
        "destination_id": resolved_destination_id,
    }


@app.get(
    "/auth/youtube/callback",
    response_class=HTMLResponse,
)
def youtube_callback(
    request: Request,
    state: str = Query(...),
    code: str = Query(...),
    destination_id: str | None = Query(
        default=None,
    ),
    pipeline_id: str | None = Query(
        default=None,
    ),
    db: Session = Depends(
        get_db
    ),
):
    from fastapi.responses import RedirectResponse

    authorization_response = str(request.url)

    try:
        complete_oauth(
            db=db,
            state=state,
            authorization_response=(
                authorization_response
            ),
            pipeline_id=pipeline_id,
            destination_id=destination_id,
        )
    except Exception as exc:
        return HTMLResponse(
            content=(
                "<h2>YouTube OAuth lỗi</h2>"
                f"<pre>{str(exc)}</pre>"
            ),
            status_code=400,
        )

    # Resolve destination/pipeline for frontend redirect.
    # Always land on the Destinations tab so the user immediately sees
    # Connected + channel title (never a dead-end page).
    resolved_destination_id = destination_id
    resolved_pipeline_id = pipeline_id

    # Best-effort: look up destination to build frontend URL.
    frontend_base = (settings.frontend_url or "").rstrip("/")
    if frontend_base and resolved_destination_id:
        destination = db.get(Destination, resolved_destination_id)
        if destination is not None:
            resolved_pipeline_id = resolved_pipeline_id or destination.pipeline_id
            return RedirectResponse(
                url=(
                    f"{frontend_base}/pipelines/{destination.pipeline_id}"
                    f"?tab=destinations&oauth=success"
                ),
                status_code=302,
            )

    if frontend_base and resolved_pipeline_id and not resolved_destination_id:
        return RedirectResponse(
            url=f"{frontend_base}/pipelines/{resolved_pipeline_id}?oauth=success",
            status_code=302,
        )

    # Fallback: try to find most recently connected destination.
    if frontend_base:
        latest = db.execute(
            select(Destination)
            .where(Destination.connected == True)  # noqa: E712
            .order_by(Destination.updated_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if latest is not None:
            return RedirectResponse(
                url=(
                    f"{frontend_base}/pipelines/{latest.pipeline_id}"
                    f"/destinations/{latest.id}?oauth=success"
                ),
                status_code=302,
            )

    return HTMLResponse(
        """
        <!doctype html>
        <html>
        <head>
          <meta charset="utf-8">
          <title>YouTube Connected</title>
        </head>
        <body style="
          font-family:Arial;
          max-width:700px;
          margin:80px auto;
        ">
          <h1>YouTube đã kết nối</h1>
          <p>
            Có thể đóng tab này và quay lại dashboard.
          </p>
        </body>
        </html>
        """
    )


# ============================================================
# Multi-destination control panel APIs
# (Pipeline -> Sources -> Inventory -> Destinations -> Publications)
# ============================================================


@app.delete(
    "/api/pipelines/{pipeline_id}",
    status_code=204,
    dependencies=[
        Depends(require_admin)
    ],
)
def delete_pipeline(
    pipeline_id: str,
    db: Session = Depends(
        get_db
    ),
) -> None:
    pipeline = db.get(Pipeline, pipeline_id)

    if pipeline is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy pipeline",
        )

    db.delete(pipeline)
    db.commit()


@app.get(
    "/api/pipelines/{pipeline_id}/stats",
    dependencies=[
        Depends(require_admin)
    ],
)
def pipeline_stats(
    pipeline_id: str,
    db: Session = Depends(
        get_db
    ),
) -> dict:
    from app.scheduler import get_next_upload_slot

    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy pipeline",
        )

    sources_count = db.execute(
        select(func.count(DouyinSource.id))
        .where(DouyinSource.pipeline_id == pipeline_id)
    ).scalar_one_or_none() or 0

    destinations = list(
        db.execute(
            select(Destination)
            .where(Destination.pipeline_id == pipeline_id)
            .order_by(Destination.created_at.asc())
        )
        .scalars()
        .all()
    )

    inventory_total = db.execute(
        select(func.count(DouyinVideo.id))
        .where(DouyinVideo.pipeline_id == pipeline_id)
    ).scalar_one_or_none() or 0

    backlog = db.execute(
        select(func.count(DouyinVideo.id))
        .where(DouyinVideo.pipeline_id == pipeline_id)
        .where(DouyinVideo.status == "backlog")
    ).scalar_one_or_none() or 0

    new_count = db.execute(
        select(func.count(DouyinVideo.id))
        .where(DouyinVideo.pipeline_id == pipeline_id)
        .where(DouyinVideo.status == "new")
    ).scalar_one_or_none() or 0

    scheduled = db.execute(
        select(func.count(DouyinVideo.id))
        .where(DouyinVideo.pipeline_id == pipeline_id)
        .where(DouyinVideo.status == "scheduled")
    ).scalar_one_or_none() or 0

    inv_published = db.execute(
        select(func.count(DouyinVideo.id))
        .where(DouyinVideo.pipeline_id == pipeline_id)
        .where(DouyinVideo.status == "published")
    ).scalar_one_or_none() or 0

    today_start = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    published_today = db.execute(
        select(func.count(Publication.id))
        .where(Publication.pipeline_id == pipeline_id)
        .where(Publication.status == "published")
        .where(Publication.published_at >= today_start)
    ).scalar_one_or_none() or 0

    failed = db.execute(
        select(func.count(Publication.id))
        .where(Publication.pipeline_id == pipeline_id)
        .where(Publication.status == "failed")
    ).scalar_one_or_none() or 0

    pub_scheduled = db.execute(
        select(func.count(Publication.id))
        .where(Publication.pipeline_id == pipeline_id)
        .where(Publication.status.in_(["scheduled", "queued"]))
    ).scalar_one_or_none() or 0

    now = _utcnow()
    next_publication = None
    for destination in destinations:
        if not destination.enabled or not destination.upload_slots:
            continue
        try:
            slot = get_next_upload_slot(
                destination.upload_slots or [],
                destination.timezone or "UTC",
                now,
            )
        except Exception:
            continue
        if slot is None:
            continue
        if next_publication is None or slot < next_publication:
            next_publication = slot

    return {
        "pipeline_id": pipeline_id,
        "sources_count": int(sources_count),
        "destinations_count": len(destinations),
        "inventory_total": int(inventory_total),
        "backlog": int(backlog),
        "new": int(new_count),
        "scheduled": int(scheduled),
        "published_inventory": int(inv_published),
        "published_today": int(published_today),
        "failed": int(failed),
        "publications_scheduled": int(pub_scheduled),
        "next_publication": next_publication.isoformat() if next_publication else None,
    }


@app.get(
    "/api/pipelines/{pipeline_id}/inventory",
    response_model=InventoryListResponse,
    dependencies=[
        Depends(require_admin)
    ],
)
def list_inventory(
    pipeline_id: str,
    source_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(
        get_db
    ),
) -> InventoryListResponse:
    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy pipeline",
        )

    query = select(DouyinVideo).where(DouyinVideo.pipeline_id == pipeline_id)
    count_query = select(func.count(DouyinVideo.id)).where(
        DouyinVideo.pipeline_id == pipeline_id
    )

    if source_id:
        query = query.where(DouyinVideo.source_id == source_id)
        count_query = count_query.where(DouyinVideo.source_id == source_id)

    if status and status != "all":
        query = query.where(DouyinVideo.status == status)
        count_query = count_query.where(DouyinVideo.status == status)

    if search:
        like = f"%{search}%"
        query = query.where(
            (DouyinVideo.title.ilike(like)) | (DouyinVideo.video_id.ilike(like))
        )
        count_query = count_query.where(
            (DouyinVideo.title.ilike(like)) | (DouyinVideo.video_id.ilike(like))
        )

    total = db.execute(count_query).scalar_one_or_none() or 0

    items = list(
        db.execute(
            query.order_by(DouyinVideo.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )

    return InventoryListResponse(
        items=[DouyinVideoOut.model_validate(v) for v in items],
        total=int(total),
        page=page,
        page_size=page_size,
    )


@app.get(
    "/api/pipelines/{pipeline_id}/inventory/{video_id}",
    response_model=DouyinVideoWithPublications,
    dependencies=[
        Depends(require_admin)
    ],
)
def get_inventory_video(
    pipeline_id: str,
    video_id: str,
    db: Session = Depends(
        get_db
    ),
) -> DouyinVideoWithPublications:
    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy pipeline",
        )

    video = db.get(DouyinVideo, video_id)
    if video is None or video.pipeline_id != pipeline_id:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy video",
        )

    publications = list(
        db.execute(
            select(Publication)
            .where(Publication.douyin_video_id == video.id)
            .order_by(Publication.created_at.asc())
        )
        .scalars()
        .all()
    )

    source_name = None
    if video.source_id:
        source = db.get(DouyinSource, video.source_id)
        if source is not None:
            source_name = source.name

    out = DouyinVideoWithPublications.model_validate(video)
    out.source_name = source_name
    out.publications = [PublicationOut.model_validate(p) for p in publications]
    return out


@app.post(
    "/api/pipelines/{pipeline_id}/inventory/{video_id}/publish",
    response_model=PublicationOut,
    status_code=201,
    dependencies=[
        Depends(require_admin)
    ],
)
def publish_inventory_video_now(
    pipeline_id: str,
    video_id: str,
    payload: PublicationPublishRequest,
    db: Session = Depends(
        get_db
    ),
) -> Publication:
    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy pipeline",
        )

    video = db.get(DouyinVideo, video_id)
    if video is None or video.pipeline_id != pipeline_id:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy video",
        )

    destination = db.get(Destination, payload.destination_id)
    if destination is None or destination.pipeline_id != pipeline_id:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy destination",
        )

    if not destination.enabled:
        raise HTTPException(
            status_code=409,
            detail="Destination đang bị pause",
        )

    if destination.platform == "facebook":
        raise HTTPException(
            status_code=400,
            detail="Facebook publishing adapter not configured",
        )

    existing = db.execute(
        select(Publication)
        .where(Publication.douyin_video_id == video.id)
        .where(Publication.destination_id == destination.id)
        .limit(1)
    ).scalar_one_or_none()

    now = _utcnow()

    if existing is not None:
        if existing.status == "published":
            raise HTTPException(
                status_code=409,
                detail="Video đã published trên destination này",
            )
        existing.status = "queued"
        existing.scheduled_at = now
        existing.error = None
        existing.attempts = 0
        publication = existing
    else:
        publication = Publication(
            pipeline_id=pipeline_id,
            douyin_video_id=video.id,
            destination_id=destination.id,
            platform=destination.platform,
            status="queued",
            scheduled_at=now,
        )
        db.add(publication)

    job = VideoJob(
        source_url=video.url,
        source_title=video.title,
        title=None,
        description=video.description,
        privacy_status=pipeline.default_privacy,
        status="pending",
        pipeline_id=pipeline_id,
        source_video_id=video.video_id,
        destination_id=destination.id,
    )
    db.add(job)
    db.flush()
    # Link Job <-> Publication so worker updates the right Publication
    # even when the same video targets multiple destinations.
    try:
        if publication.id is not None:
            job.publication_id = publication.id
            db.flush()
    except Exception:
        pass
    db.commit()
    db.refresh(publication)

    return publication


@app.post(
    "/api/sources/{source_id}/sync",
    response_model=SourceSyncResponse,
    status_code=202,
    dependencies=[
        Depends(require_admin)
    ],
)
def sync_source_now(
    source_id: str,
    db: Session = Depends(
        get_db
    ),
) -> SourceSyncResponse:
    """Queue a source sync and return <500ms. Worker runs in background.

    Flow: queued -> running -> completed/failed/auth_required.
    Dashboard must poll GET /api/sources/{id} every 2-5s.
    """
    source = db.get(DouyinSource, source_id)
    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy source",
        )

    source.inventory_sync_status = "queued"
    source.inventory_sync_error = None
    db.commit()

    import threading as _threading

    _threading.Thread(
        target=trigger_inventory_sync_job, args=(source_id, "full"), daemon=True
    ).start()
    return SourceSyncResponse(
        source_id=source.id,
        status="queued",
        new=0,
        updated=0,
    )


@app.post(
    "/api/sources/{source_id}/initial-import",
    response_model=SourceImportResponse,
    status_code=202,
    dependencies=[
        Depends(require_admin)
    ],
)
def start_initial_import(
    source_id: str,
    db: Session = Depends(get_db),
) -> SourceImportResponse:
    """Start the one-off full backlog import (pages until has_more=false).

    Runs in the background; dashboard polls GET /api/sources/{id} and can read
    progress from initial_import_status/initial_import_pages. No RapidAPI
    request is spent if quota is already at the safety floor.
    """
    from app import douyin_import

    source = db.get(DouyinSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy source")

    quota = douyin_import.quota_status()
    if not douyin_quota_can_start():
        raise HTTPException(
            status_code=429,
            detail="RAPIDAPI_QUOTA_EXHAUSTED: hết quota RapidAPI tháng này",
        )

    source.initial_import_status = "running"
    source.initial_import_last_error = None
    source.inventory_sync_status = "queued"
    source.inventory_sync_error = None
    db.commit()

    import threading as _threading

    _threading.Thread(
        target=trigger_inventory_sync_job, args=(source_id, "full"), daemon=True
    ).start()
    return SourceImportResponse(
        source_id=source_id, status="queued", quota=DouyinQuotaOut(**quota)
    )


@app.post(
    "/api/sources/{source_id}/initial-import/resume",
    response_model=SourceImportResponse,
    status_code=202,
    dependencies=[
        Depends(require_admin)
    ],
)
def resume_initial_import(
    source_id: str,
    db: Session = Depends(get_db),
) -> SourceImportResponse:
    """Resume a paused import from the stored cursor instead of page 1."""
    from app import douyin_import

    source = db.get(DouyinSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy source")
    if not source.initial_import_cursor:
        raise HTTPException(
            status_code=409,
            detail="Không có cursor để chạy tiếp — chạy import từ đầu",
        )

    quota = douyin_import.quota_status()
    if not douyin_quota_can_start():
        raise HTTPException(
            status_code=429,
            detail="RAPIDAPI_QUOTA_EXHAUSTED: hết quota RapidAPI tháng này",
        )

    source.initial_import_status = "running"
    source.initial_import_last_error = None
    source.inventory_sync_status = "queued"
    source.inventory_sync_error = None
    db.commit()

    import threading as _threading

    _threading.Thread(
        target=trigger_inventory_sync_job, args=(source_id, "resume"), daemon=True
    ).start()
    return SourceImportResponse(
        source_id=source_id, status="queued", cursor=source.initial_import_cursor,
        quota=DouyinQuotaOut(**quota),
    )


@app.post(
    "/api/sources/{source_id}/refresh",
    response_model=SourceImportResponse,
    status_code=202,
    dependencies=[
        Depends(require_admin)
    ],
)
def refresh_source_now(
    source_id: str,
    db: Session = Depends(get_db),
) -> SourceImportResponse:
    """Manual refresh: page 1 newest-first, stop at the first known video."""
    from app import douyin_import

    source = db.get(DouyinSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy source")

    quota = douyin_import.quota_status()
    if not douyin_quota_can_start():
        raise HTTPException(
            status_code=429,
            detail="RAPIDAPI_QUOTA_EXHAUSTED: hết quota RapidAPI tháng này",
        )

    source.inventory_sync_status = "queued"
    source.inventory_sync_error = None
    db.commit()

    import threading as _threading

    _threading.Thread(
        target=trigger_inventory_sync_job, args=(source_id, "latest"), daemon=True
    ).start()
    return SourceImportResponse(
        source_id=source_id, status="queued", quota=DouyinQuotaOut(**quota)
    )


@app.get(
    "/api/sources/{source_id}/inventory",
    response_model=SourceInventoryResponse,
    dependencies=[
        Depends(require_admin)
    ],
)
def get_source_inventory(
    source_id: str,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> SourceInventoryResponse:
    """Inventory rows for one source (admin import result)."""
    source = db.get(DouyinSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy source")

    from app import douyin_import

    data = douyin_import.list_source_inventory(
        source_id, limit=limit, offset=offset
    )
    return SourceInventoryResponse(**data)


@app.get(
    "/api/douyin/quota",
    response_model=DouyinQuotaOut,
    dependencies=[
        Depends(require_admin)
    ],
)
def get_douyin_quota() -> DouyinQuotaOut:
    """RapidAPI quota snapshot for the dashboard. Contains no secrets."""
    from app import douyin_import

    return DouyinQuotaOut(**douyin_import.quota_status())


@app.post(
    "/api/pipelines/{pipeline_id}/sync",
    status_code=202,
    dependencies=[
        Depends(require_admin)
    ],
)
def sync_pipeline_now(
    pipeline_id: str,
    db: Session = Depends(
        get_db
    ),
) -> dict:
    """Queue pipeline-wide sync, return immediately. Background worker scans."""
    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy pipeline",
        )

    sources = list(
        db.execute(
            select(DouyinSource)
            .where(DouyinSource.pipeline_id == pipeline_id)
            .where(DouyinSource.enabled == True)  # noqa: E712
        )
        .scalars()
        .all()
    )
    for s in sources:
        s.inventory_sync_status = "queued"
        s.inventory_sync_error = None
    db.commit()
    source_ids = [s.id for s in sources]

    import threading as _threading

    def _bg_pipeline_sync() -> None:
        try:
            from app.inventory import sync_source_inventory

            for sid in source_ids:
                try:
                    sync_source_inventory(sid, mode="full")
                except Exception:
                    logger.exception("Pipeline sync failed for source %s", sid)
        except Exception:
            logger.exception("Pipeline background sync failed %s", pipeline_id)

    _threading.Thread(target=_bg_pipeline_sync, daemon=True).start()
    return {"status": "queued", "new": 0, "updated": 0, "sources": len(source_ids)}


@app.get(
    "/api/system/douyin-session",
    dependencies=[
        Depends(require_admin)
    ],
)
def douyin_session_status() -> dict:
    """Cookie/session status only. Never returns cookie values.

    Does NOT launch a browser: anonymous_access/cookie_required reflect
    the last real profile scan outcome (None when no scan has run yet).
    """
    from app.douyin_inventory_providers import (
        cookies_configured,
        cookies_look_expired,
        get_last_access_probe,
        parse_netscape_cookies,
    )

    configured = cookies_configured()
    probe = get_last_access_probe()
    anonymous_access = probe["anonymous_ok"] if probe else None
    cookie_required = probe["cookie_required"] if probe else None

    if not configured:
        return {
            "configured": False,
            "cookie_configured": False,
            "anonymous_access": anonymous_access,
            "cookie_required": cookie_required,
            "last_validation": _utcnow().isoformat(),
            "valid": False,
            "error": "DOUYIN_COOKIES_B64 not configured (optional; needed only if anonymous access is blocked)",
        }

    try:
        from app.douyin_inventory_providers import decode_netscape_cookies_raw

        text = decode_netscape_cookies_raw()
        parsed = parse_netscape_cookies(text)
        if not parsed:
            return {
                "configured": True,
                "cookie_configured": True,
                "anonymous_access": anonymous_access,
                "cookie_required": cookie_required,
                "last_validation": _utcnow().isoformat(),
                "valid": False,
                "error": "Douyin session expired",
            }
        if cookies_look_expired(parsed):
            return {
                "configured": True,
                "cookie_configured": True,
                "anonymous_access": anonymous_access,
                "cookie_required": cookie_required,
                "last_validation": _utcnow().isoformat(),
                "valid": False,
                "error": "Douyin session expired",
            }
        return {
            "configured": True,
            "cookie_configured": True,
            "anonymous_access": anonymous_access,
            "cookie_required": cookie_required,
            "last_validation": _utcnow().isoformat(),
            "valid": True,
        }
    except Exception as exc:
        return {
            "configured": True,
            "cookie_configured": True,
            "anonymous_access": anonymous_access,
            "cookie_required": cookie_required,
            "last_validation": _utcnow().isoformat(),
            "valid": False,
            "error": str(exc)[:500],
        }


@app.post(
    "/api/douyin/session/start",
    status_code=201,
    dependencies=[
        Depends(require_admin)
    ],
)
def douyin_session_start() -> dict:
    """Queue a QR login flow, return session_id immediately.

    QR capture runs in background; dashboard polls
    GET /api/douyin/session/{id}/status every few seconds.
    Never blocks the page on Playwright launch.
    """
    from app.douyin_session import queue_login_flow

    try:
        return queue_login_flow()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/api/douyin/session/status",
    dependencies=[
        Depends(require_admin)
    ],
)
def douyin_session_aggregate() -> dict:
    from app.douyin_session import get_aggregate_status

    return get_aggregate_status()


@app.get(
    "/api/douyin/session/{session_id}/status",
    dependencies=[
        Depends(require_admin)
    ],
)
def douyin_session_flow_status(session_id: str) -> dict:
    from app.douyin_session import get_flow_status

    try:
        return get_flow_status(session_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Không tìm thấy Douyin session"
        ) from exc


@app.post(
    "/api/douyin/session/validate",
    dependencies=[
        Depends(require_admin)
    ],
)
def douyin_session_validate() -> dict:
    from app.douyin_session import validate_saved_session

    try:
        return validate_saved_session()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post(
    "/api/douyin/session/disconnect",
    dependencies=[
        Depends(require_admin)
    ],
)
def douyin_session_disconnect(
    session_id: str | None = Query(default=None),
) -> dict:
    from app.douyin_session import disconnect_session

    removed = disconnect_session(session_id)
    return {"removed": int(removed)}


@app.get(
    "/api/publications/{publication_id}",
    response_model=PublicationOut,
    dependencies=[
        Depends(require_admin)
    ],
)
def get_publication(
    publication_id: str,
    db: Session = Depends(
        get_db
    ),
) -> Publication:
    publication = db.get(Publication, publication_id)
    if publication is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy publication",
        )
    return publication


@app.post(
    "/api/publications/{publication_id}/retry",
    response_model=PublicationOut,
    dependencies=[
        Depends(require_admin)
    ],
)
def retry_publication(
    publication_id: str,
    db: Session = Depends(
        get_db
    ),
) -> Publication:
    publication = db.get(Publication, publication_id)
    if publication is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy publication",
        )

    if publication.status not in {"failed", "skipped", "queued", "scheduled"}:
        raise HTTPException(
            status_code=409,
            detail="Chỉ retry publication đang failed/skipped/queued/scheduled",
        )

    if publication.status == "published":
        raise HTTPException(
            status_code=409,
            detail="Publication đã published",
        )

    destination = db.get(Destination, publication.destination_id)
    if destination is not None and destination.platform == "facebook":
        raise HTTPException(
            status_code=400,
            detail="Facebook publishing adapter not configured",
        )

    publication.status = "queued"
    publication.error = None
    publication.attempts = 0
    publication.scheduled_at = _utcnow()

    # Enqueue a worker job scoped to this destination so retry actually publishes.
    video = db.get(DouyinVideo, publication.douyin_video_id)
    pipeline = db.get(Pipeline, publication.pipeline_id)
    if video is not None and pipeline is not None:
        job = VideoJob(
            source_url=video.url,
            source_title=video.title,
            title=publication.title,
            description=publication.description or video.description,
            privacy_status=pipeline.default_privacy,
            status="pending",
            pipeline_id=pipeline.id,
            source_video_id=video.video_id,
            destination_id=publication.destination_id,
            publication_id=publication.id,
        )
        db.add(job)

    db.commit()
    db.refresh(publication)
    return publication


@app.post(
    "/api/publications/{publication_id}/skip",
    response_model=PublicationOut,
    dependencies=[
        Depends(require_admin)
    ],
)
def skip_publication(
    publication_id: str,
    db: Session = Depends(
        get_db
    ),
) -> Publication:
    publication = db.get(Publication, publication_id)
    if publication is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy publication",
        )

    if publication.status == "published":
        raise HTTPException(
            status_code=409,
            detail="Không thể skip publication đã published",
        )

    publication.status = "skipped"
    db.commit()
    db.refresh(publication)
    return publication


@app.post(
    "/api/publications/{publication_id}/reschedule",
    response_model=PublicationOut,
    dependencies=[
        Depends(require_admin)
    ],
)
def reschedule_publication(
    publication_id: str,
    payload: PublicationRescheduleRequest,
    db: Session = Depends(
        get_db
    ),
) -> Publication:
    publication = db.get(Publication, publication_id)
    if publication is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy publication",
        )

    if publication.status == "published":
        raise HTTPException(
            status_code=409,
            detail="Không thể reschedule publication đã published",
        )

    publication.status = "scheduled"
    publication.scheduled_at = payload.scheduled_at
    publication.error = None
    db.commit()
    db.refresh(publication)
    return publication


@app.get(
    "/api/pipelines/{pipeline_id}/scheduler-status",
    dependencies=[
        Depends(require_admin)
    ],
)
def pipeline_scheduler_status(
    pipeline_id: str,
    db: Session = Depends(
        get_db
    ),
) -> dict:
    """Scheduler observability: why auto-publish did/did not run.

    Reason codes: NO_AVAILABLE_INVENTORY, DESTINATION_NOT_CONNECTED,
    DAILY_LIMIT_REACHED, WAITING_NEXT_SLOT, SCHEDULER_DISABLED, WORKER_ERROR.
    """
    from app.scheduler import (
        count_inventory_available,
        count_todays_released_jobs,
        get_local_day_bounds,
        get_next_upload_slot,
        get_slots_between,
    )

    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy pipeline",
        )

    now = _utcnow()
    destinations = list(
        db.execute(
            select(Destination)
            .where(Destination.pipeline_id == pipeline_id)
            .order_by(Destination.created_at.asc())
        )
        .scalars()
        .all()
    )

    inventory_available = count_inventory_available(db, pipeline)
    connected = [
        d for d in destinations
        if d.enabled and d.connected and d.credentials
        and (d.platform or "").lower() == "youtube"
    ]

    last_cycle = None
    last_job_created = None
    for d in destinations:
        for cand in (d.last_cycle_at, d.last_scheduler_check_at):
            if cand is not None:
                if cand.tzinfo is None:
                    cand = cand.replace(tzinfo=timezone.utc)
                if last_cycle is None or cand > last_cycle:
                    last_cycle = cand
        if d.last_job_created_at is not None:
            cand = d.last_job_created_at
            if cand.tzinfo is None:
                cand = cand.replace(tzinfo=timezone.utc)
            if last_job_created is None or cand > last_job_created:
                last_job_created = cand
    # Fallback to newest job/publication when destination fields are null
    # (e.g. before first scheduler cycle after deploy).
    if last_job_created is None:
        newest_job = db.execute(
            select(func.max(VideoJob.created_at))
            .where(VideoJob.pipeline_id == pipeline_id)
        ).scalar_one_or_none()
        newest_pub = db.execute(
            select(func.max(Publication.created_at))
            .where(Publication.pipeline_id == pipeline_id)
        ).scalar_one_or_none()
        for cand in (newest_job, newest_pub):
            if cand is not None:
                if cand.tzinfo is None:
                    cand = cand.replace(tzinfo=timezone.utc)
                if last_job_created is None or cand > last_job_created:
                    last_job_created = cand

    next_slots: list[str] = []
    try:
        for d in destinations:
            if not d.enabled or not (d.upload_slots or []):
                continue
            nxt = get_next_upload_slot(
                d.upload_slots or [], d.timezone or "UTC", now
            )
            if nxt is not None:
                next_slots.append(nxt.isoformat())
        next_slots = sorted(set(next_slots))
    except Exception:
        pass

    today_rows: list[dict] = []
    for d in destinations:
        try:
            day_start, _ = get_local_day_bounds(d.timezone or "UTC", now)
        except Exception:
            day_start = now.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        published = db.execute(
            select(func.count(Publication.id))
            .where(Publication.destination_id == d.id)
            .where(Publication.status == "published")
            .where(Publication.published_at >= day_start)
        ).scalar_one_or_none() or 0
        released = count_todays_released_jobs(db, pipeline, day_start, d)
        try:
            nxt = get_next_upload_slot(
                d.upload_slots or [], d.timezone or "UTC", now
            )
            nxt_iso = nxt.isoformat() if nxt is not None else None
        except Exception:
            nxt_iso = None
        reason = d.last_skip_reason
        # Derive live reason when no stored reason yet.
        if not reason:
            if not pipeline.enabled:
                reason = "SCHEDULER_DISABLED"
            elif not (d.enabled and d.connected and d.credentials):
                reason = "DESTINATION_NOT_CONNECTED"
            elif int(released or 0) >= int(d.daily_upload_limit or 6):
                reason = "DAILY_LIMIT_REACHED"
            elif int(inventory_available or 0) <= 0:
                reason = "NO_AVAILABLE_INVENTORY"
            else:
                reason = "WAITING_NEXT_SLOT"
        today_rows.append({
            "destination_id": d.id,
            "destination_name": d.name,
            "platform": d.platform,
            "enabled": bool(d.enabled),
            "connected": bool(d.connected),
            "published": int(published or 0),
            "released": int(released or 0),
            "limit": int(d.daily_upload_limit or 6),
            "next_slot": nxt_iso,
            "last_skip_reason": reason,
            "last_check_at": (
                d.last_scheduler_check_at.isoformat()
                if d.last_scheduler_check_at is not None else None
            ),
            "last_job_created_at": (
                d.last_job_created_at.isoformat()
                if d.last_job_created_at is not None else None
            ),
        })

    return {
        "enabled": bool(
            pipeline.enabled and getattr(
                __import__("app.config", fromlist=["settings"]).settings,
                "scheduler_enabled", True,
            )
        ),
        "pipeline_enabled": bool(pipeline.enabled),
        "last_cycle_at": last_cycle.isoformat() if last_cycle else None,
        "last_job_created_at": (
            last_job_created.isoformat() if last_job_created else None
        ),
        "next_slots": next_slots,
        "inventory_available": int(inventory_available or 0),
        "connected_destinations": len(connected),
        "destinations_total": len(destinations),
        "today": today_rows,
    }


def resolve_douyin_input(raw_input: str) -> dict[str, Any]:
    """Resolve Douyin input (URL or full share text).

    Returns video info or profile detection response.
    """
    clean_text = raw_input.strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="Vui lòng nhập link hoặc nội dung chia sẻ Douyin")

    # Extract URL from share text
    url_match = re.search(r"https?://[^\s<>'\"\)\]]+", clean_text)
    if not url_match:
        url_match = re.search(r"(?:v\.douyin\.com|[a-zA-Z0-9-]+\.douyin\.com)/[^\s<>'\"\)\]]+", clean_text)
        if url_match:
            source_url = "https://" + url_match.group(0)
        else:
            raise HTTPException(status_code=400, detail="Không tìm thấy link Douyin hợp lệ trong nội dung")
    else:
        source_url = url_match.group(0)

    # 1. Direct profile check
    prof = parse_douyin_profile_url(source_url)
    if prof is not None:
        return {
            "type": "profile",
            "source_url": source_url,
            "message": "This is a Douyin profile, not a single video.",
            "profile_url": prof.canonical,
            "sec_uid": prof.sec_uid,
            "status": "Profile detected",
        }

    # 2. Follow redirect with mobile UA
    final_url = source_url
    try:
        req = urllib.request.Request(
            source_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
                    "Mobile/15E148 Safari/604.1"
                )
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            final_url = resp.geturl()
    except Exception as exc:
        logger.warning("Failed to follow redirect for %s: %s", source_url, exc)

    # 3. Check redirected URL for profile
    prof_redirect = parse_douyin_profile_url(final_url)
    if prof_redirect is not None or "/user/" in final_url or "/share/user/" in final_url:
        sec_uid = prof_redirect.sec_uid if prof_redirect else None
        if not sec_uid:
            sm = re.search(r"/user/([A-Za-z0-9_-]+)", final_url) or re.search(r"/share/user/([A-Za-z0-9_-]+)", final_url)
            sec_uid = sm.group(1) if sm else None
        canonical = prof_redirect.canonical if prof_redirect else f"https://www.douyin.com/user/{sec_uid or ''}"
        return {
            "type": "profile",
            "source_url": source_url,
            "message": "This is a Douyin profile, not a single video.",
            "profile_url": canonical,
            "sec_uid": sec_uid,
            "status": "Profile detected",
        }

    # 4. Extract video ID
    vid_match = re.search(r"/(?:video|note)/(\d+)", final_url)
    video_id = vid_match.group(1) if vid_match else None
    if not video_id:
        im = re.search(r"item_ids?=(\d+)", final_url)
        video_id = im.group(1) if im else None

    # 5. Extract author from share text if available
    author_match = (
        re.search(r"看看【([^】]+)的作品】", clean_text)
        or re.search(r"【([^】]+)的作品】", clean_text)
    )
    author = author_match.group(1).strip() if author_match else None

    # 6. Call Rcuts parser (primary first, fallback second)
    caption = None
    thumbnail = None
    video_url = None
    primary_api = settings.rcuts_primary_api_url or settings.rcuts_api_url
    fallback_api = settings.rcuts_fallback_api_url or settings.rcuts_api_url

    for api_url in [primary_api, fallback_api]:
        if not api_url:
            continue
        try:
            data = call_rcuts_parser(api_url, source_url, share_text=clean_text)
            if data and isinstance(data, dict):
                caption = data.get("video_name") or data.get("title") or data.get("desc")
                thumbnail = data.get("cover") or data.get("sound_cover")
                video_url = data.get("video_url")
                if not author:
                    author = data.get("nickname") or data.get("author")
                if caption or thumbnail or video_url:
                    break
        except Exception as exc:
            logger.warning("Rcuts parser %s failed for %s: %s", api_url, source_url, exc)

    # 7. Fallback caption from share text if Rcuts returned empty
    if not caption:
        cleaned_caption = re.sub(r"https?://[^\s]+", "", clean_text)
        cleaned_caption = cleaned_caption.replace("复制打开抖音", "")
        cleaned_caption = re.sub(r"看看【.*?的作品】", "", cleaned_caption).strip()
        if cleaned_caption:
            caption = cleaned_caption

    # 8. Extract duration via quick ffprobe if video_url available
    duration = None
    if video_url:
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_url,
            ]
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
            dur_text = p.stdout.strip()
            if dur_text:
                duration = int(round(float(dur_text)))
        except Exception:
            pass

    return {
        "type": "video",
        "source_url": source_url,
        "video_id": video_id,
        "author": author or "Douyin Creator",
        "caption": caption or "",
        "thumbnail": thumbnail,
        "duration": duration,
        "status": "Video detected",
    }


@app.post(
    "/api/manual/resolve",
    response_model=ManualResolveResponse,
    dependencies=[Depends(require_admin)],
)
def manual_resolve_endpoint(
    payload: ManualResolveRequest,
) -> ManualResolveResponse:
    res = resolve_douyin_input(payload.input)
    return ManualResolveResponse(**res)


@app.post(
    "/api/manual/metadata",
    response_model=ManualMetadataResponse,
    dependencies=[Depends(require_admin)],
)
def manual_metadata_endpoint(
    payload: ManualMetadataRequest,
    db: Session = Depends(get_db),
) -> ManualMetadataResponse:
    destinations: list[Destination] = []
    if payload.destination_ids:
        for did in payload.destination_ids:
            d = db.get(Destination, did)
            if d is not None:
                destinations.append(d)

    context_text = (payload.caption or "").strip() or payload.source_url

    if payload.metadata_mode == "separate" and len(destinations) > 1:
        by_destination: dict[str, ManualMetadataItem] = {}
        for dest in destinations:
            pipeline = db.get(Pipeline, dest.pipeline_id) if dest.pipeline_id else None
            gen = generate_metadata_structured(
                context_text=context_text,
                pipeline=pipeline,
                destination=dest,
            )
            if gen:
                by_destination[dest.id] = ManualMetadataItem(
                    title=gen["title"],
                    description=gen["description"],
                    hashtags=gen["hashtags"],
                    final_description=gen["final_description"],
                    content_match=gen.get("content_match"),
                    content_match_reason=gen.get("content_match_reason"),
                    match_level=gen.get("match_level"),
                )
        return ManualMetadataResponse(
            metadata_mode="separate",
            by_destination=by_destination,
        )

    # Mode: same (generate once using first destination or default pipeline)
    first_dest = destinations[0] if destinations else None
    pipeline = db.get(Pipeline, first_dest.pipeline_id) if (first_dest and first_dest.pipeline_id) else None
    if pipeline is None:
        pipeline = db.execute(select(Pipeline).order_by(Pipeline.created_at.asc()).limit(1)).scalar_one_or_none()

    gen = generate_metadata_structured(
        context_text=context_text,
        pipeline=pipeline,
        destination=first_dest,
    )
    same_item = None
    if gen:
        same_item = ManualMetadataItem(
            title=gen["title"],
            description=gen["description"],
            hashtags=gen["hashtags"],
            final_description=gen["final_description"],
            content_match=gen.get("content_match"),
            content_match_reason=gen.get("content_match_reason"),
            match_level=gen.get("match_level"),
        )

    return ManualMetadataResponse(
        metadata_mode="same",
        same=same_item,
    )


@app.post(
    "/api/manual/publish",
    response_model=ManualPublishResponse,
    status_code=202,
    dependencies=[Depends(require_admin)],
)
def manual_publish_endpoint(
    payload: ManualPublishRequest,
    db: Session = Depends(get_db),
) -> ManualPublishResponse:
    if not payload.destination_ids:
        raise HTTPException(status_code=400, detail="Vui lòng chọn ít nhất một destination")

    destinations: list[Destination] = []
    for did in payload.destination_ids:
        dest = db.get(Destination, did)
        if dest is None:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy destination id={did}")
        if not dest.enabled:
            raise HTTPException(status_code=409, detail=f"Destination '{dest.name}' đang bị tạm dừng (paused)")
        if dest.platform == "facebook":
            raise HTTPException(status_code=400, detail=f"Destination '{dest.name}' (Facebook): publishing adapter chưa được cấu hình")
        if dest.platform == "youtube":
            if not dest.connected or not dest.credentials:
                raise HTTPException(status_code=400, detail=f"Destination '{dest.name}' (YouTube) chưa kết nối OAuth")
        destinations.append(dest)

    # Duplicate protection check (Requirement 16)
    if not payload.force_duplicate and payload.video_id:
        for dest in destinations:
            existing = db.execute(
                select(Publication)
                .join(DouyinVideo, Publication.douyin_video_id == DouyinVideo.id)
                .where(Publication.destination_id == dest.id)
                .where(Publication.status == "published")
                .where(
                    (DouyinVideo.video_id == payload.video_id)
                    | (DouyinVideo.url == payload.source_url)
                )
                .limit(1)
            ).scalar_one_or_none()
            if existing is not None:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "DUPLICATE_VIDEO",
                        "message": f"This video was already published to {dest.name}.",
                        "destination_id": dest.id,
                        "destination_name": dest.name,
                        "external_url": existing.external_url,
                        "published_at": existing.published_at.isoformat() if existing.published_at else None,
                    },
                )

    created_publications: list[ManualPublicationItem] = []
    now = _utcnow()

    for dest in destinations:
        pipeline = db.get(Pipeline, dest.pipeline_id) if dest.pipeline_id else None
        if pipeline is None:
            pipeline = db.execute(select(Pipeline).order_by(Pipeline.created_at.asc()).limit(1)).scalar_one_or_none()
        if pipeline is None:
            raise HTTPException(status_code=500, detail="Không tìm thấy pipeline phù hợp")

        # Strict Cross-Workspace Validation (Requirement 15):
        if payload.video_id:
            existing_other = db.execute(
                select(DouyinVideo)
                .where(DouyinVideo.video_id == payload.video_id)
                .where(DouyinVideo.pipeline_id != pipeline.id)
                .limit(1)
            ).scalar_one_or_none()
            if existing_other is not None:
                raise HTTPException(
                    status_code=403,
                    detail=f"Cross-workspace mismatch: video {payload.video_id} belongs to pipeline {existing_other.pipeline_id}, not destination workspace {pipeline.id}",
                )

        video_id_val = payload.video_id or str(uuid.uuid4())[:12]
        video = db.execute(
            select(DouyinVideo)
            .where(DouyinVideo.pipeline_id == pipeline.id)
            .where(DouyinVideo.video_id == video_id_val)
            .limit(1)
        ).scalar_one_or_none()

        dest_meta = payload.destinations_metadata.get(dest.id) if payload.metadata_mode == "separate" else None
        title = (dest_meta.title if dest_meta else payload.title) or payload.source_title or ""
        description = (dest_meta.description if dest_meta else payload.description) or ""

        if video is None:
            video = DouyinVideo(
                pipeline_id=pipeline.id,
                source_id=None,
                video_id=video_id_val,
                title=title or payload.source_title or "",
                description=description or "",
                url=payload.source_url,
                thumbnail_url=payload.thumbnail,
                status="inventory",
            )
            db.add(video)
            db.flush()
        else:
            if payload.thumbnail and not video.thumbnail_url:
                video.thumbnail_url = payload.thumbnail
                db.flush()

        # Find or create Publication
        pub = db.execute(
            select(Publication)
            .where(Publication.douyin_video_id == video.id)
            .where(Publication.destination_id == dest.id)
            .limit(1)
        ).scalar_one_or_none()

        if pub is None:
            pub = Publication(
                pipeline_id=pipeline.id,
                douyin_video_id=video.id,
                destination_id=dest.id,
                platform=dest.platform,
                publication_mode="manual",
                status="queued",
                scheduled_at=now,
                title=title,
                description=description,
            )
            db.add(pub)
            db.flush()
        else:
            pub.publication_mode = "manual"
            pub.status = "queued"
            pub.error = None
            pub.attempts = 0
            pub.scheduled_at = now
            pub.title = title
            pub.description = description
            db.flush()

        privacy = payload.privacy_status or pipeline.default_privacy

        job = VideoJob(
            source_url=payload.source_url,
            source_title=payload.source_title or video.title,
            title=title,
            description=description,
            privacy_status=privacy,
            status="pending",
            pipeline_id=pipeline.id,
            destination_id=dest.id,
            publication_id=pub.id,
            source_video_id=video.video_id,
        )
        db.add(job)
        db.flush()

        created_publications.append(
            ManualPublicationItem(
                id=pub.id,
                destination_id=dest.id,
                destination_name=dest.name,
                platform=dest.platform,
                status="queued",
                progress=0,
                video_title=title or video.title,
                source_url=payload.source_url,
                thumbnail=video.thumbnail_url or payload.thumbnail,
                external_url=pub.external_url,
                error=None,
                created_at=pub.created_at,
                published_at=pub.published_at,
            )
        )

    db.commit()

    return ManualPublishResponse(
        accepted=True,
        publications=created_publications,
    )


@app.get(
    "/api/manual/publications",
    response_model=list[ManualPublicationItem],
    dependencies=[Depends(require_admin)],
)
def list_manual_publications_endpoint(
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[ManualPublicationItem]:
    pubs = list(
        db.execute(
            select(Publication)
            .where(Publication.publication_mode == "manual")
            .order_by(Publication.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )

    items: list[ManualPublicationItem] = []
    for p in pubs:
        dest = db.get(Destination, p.destination_id)
        video = db.get(DouyinVideo, p.douyin_video_id)
        job = db.execute(
            select(VideoJob)
            .where(VideoJob.publication_id == p.id)
            .order_by(VideoJob.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        status = p.status
        progress = 0
        if job is not None:
            progress = job.progress or 0
            if status in ("queued", "downloading", "uploading", "ai_metadata") and job.status != "pending":
                status = job.status

        items.append(
            ManualPublicationItem(
                id=p.id,
                destination_id=p.destination_id,
                destination_name=dest.name if dest else "—",
                platform=p.platform,
                status=status,
                progress=progress,
                video_title=p.title or (video.title if video else None),
                source_url=video.url if video else None,
                thumbnail=video.thumbnail_url if video else None,
                external_url=p.external_url,
                error=p.error or (job.error if job else None),
                created_at=p.created_at,
                published_at=p.published_at,
            )
        )

    return items


@app.get(
    "/api/manual/publications/{publication_id}",
    response_model=ManualPublicationItem,
    dependencies=[Depends(require_admin)],
)
def get_manual_publication_endpoint(
    publication_id: str,
    db: Session = Depends(get_db),
) -> ManualPublicationItem:
    p = db.get(Publication, publication_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy publication")

    dest = db.get(Destination, p.destination_id)
    video = db.get(DouyinVideo, p.douyin_video_id)
    job = db.execute(
        select(VideoJob)
        .where(VideoJob.publication_id == p.id)
        .order_by(VideoJob.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    status = p.status
    progress = 0
    if job is not None:
        progress = job.progress or 0
        if status in ("queued", "downloading", "uploading", "ai_metadata") and job.status != "pending":
            status = job.status

    return ManualPublicationItem(
        id=p.id,
        destination_id=p.destination_id,
        destination_name=dest.name if dest else "—",
        platform=p.platform,
        status=status,
        progress=progress,
        video_title=p.title or (video.title if video else None),
        source_url=video.url if video else None,
        thumbnail=video.thumbnail_url if video else None,
        external_url=p.external_url,
        error=p.error or (job.error if job else None),
        created_at=p.created_at,
        published_at=p.published_at,
    )


@app.post(
    "/api/manual/publications/{publication_id}/retry",
    response_model=ManualPublicationItem,
    dependencies=[Depends(require_admin)],
)
def retry_manual_publication_endpoint(
    publication_id: str,
    db: Session = Depends(get_db),
) -> ManualPublicationItem:
    p = db.get(Publication, publication_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy publication")

    if p.status == "published":
        raise HTTPException(status_code=409, detail="Publication đã published")

    dest = db.get(Destination, p.destination_id)
    if dest is not None and dest.platform == "facebook":
        raise HTTPException(status_code=400, detail="Facebook publishing adapter not configured")

    p.status = "queued"
    p.error = None
    p.attempts = 0
    p.scheduled_at = _utcnow()
    p.publication_mode = "manual"

    video = db.get(DouyinVideo, p.douyin_video_id)
    pipeline = db.get(Pipeline, p.pipeline_id)
    if video is not None and pipeline is not None and dest is not None:
        job = VideoJob(
            source_url=video.url,
            source_title=video.title,
            title=p.title,
            description=p.description or video.description,
            privacy_status=pipeline.default_privacy,
            status="pending",
            pipeline_id=pipeline.id,
            source_video_id=video.video_id,
            destination_id=dest.id,
            publication_id=p.id,
        )
        db.add(job)

    db.commit()
    db.refresh(p)

    return ManualPublicationItem(
        id=p.id,
        destination_id=p.destination_id,
        destination_name=dest.name if dest else "—",
        platform=p.platform,
        status="queued",
        progress=0,
        video_title=p.title or (video.title if video else None),
        source_url=video.url if video else None,
        thumbnail=video.thumbnail_url if video else None,
        external_url=p.external_url,
        error=None,
        created_at=p.created_at,
        published_at=p.published_at,
    )


@app.get(
    "/api/channels",
    response_model=list[ChannelItem],
    dependencies=[Depends(require_admin)],
)
def list_channels_endpoint(
    db: Session = Depends(get_db),
) -> list[ChannelItem]:
    dests = (
        db.execute(
            select(Destination)
            .where(Destination.platform == "youtube")
            .order_by(Destination.name.asc())
        )
        .scalars()
        .all()
    )

    if not dests:
        return []

    dest_ids = [d.id for d in dests]
    pipeline_ids = list({d.pipeline_id for d in dests if d.pipeline_id})

    pipelines_map = {}
    if pipeline_ids:
        pipes = (
            db.execute(select(Pipeline).where(Pipeline.id.in_(pipeline_ids)))
            .scalars()
            .all()
        )
        pipelines_map = {p.id: p for p in pipes}

    now_utc = datetime.now(timezone.utc)
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

    agg_rows = db.execute(
        select(
            Publication.destination_id,
            func.count(Publication.id)
            .filter(
                Publication.status == "published",
                Publication.published_at >= today_start,
            )
            .label("published_today"),
            func.count(Publication.id)
            .filter(
                Publication.status.in_(
                    [
                        "queued",
                        "pending",
                        "downloading",
                        "ai_metadata",
                        "uploading",
                    ]
                )
            )
            .label("queue_count"),
            func.max(Publication.published_at)
            .filter(Publication.status == "published")
            .label("last_published_at"),
        )
        .where(Publication.destination_id.in_(dest_ids))
        .group_by(Publication.destination_id)
    ).all()

    stats_map = {
        row.destination_id: {
            "published_today": row.published_today or 0,
            "queue_count": row.queue_count or 0,
            "last_published_at": row.last_published_at,
        }
        for row in agg_rows
    }

    result: list[ChannelItem] = []
    for d in dests:
        pipe = pipelines_map.get(d.pipeline_id)
        stat = stats_map.get(
            d.id,
            {
                "published_today": 0,
                "queue_count": 0,
                "last_published_at": None,
            },
        )

        avatar_url = None
        if d.credentials:
            try:
                c = json.loads(d.credentials)
                avatar_url = c.get("avatar_url")
            except Exception:
                pass

        channel_title = d.external_account_name or d.name
        channel_id = d.external_account_id

        result.append(
            ChannelItem(
                id=d.id,
                destination_id=d.id,
                pipeline_id=d.pipeline_id,
                pipeline_name=pipe.name if pipe else d.pipeline_id,
                channel_id=channel_id,
                channel_title=channel_title,
                avatar_url=avatar_url,
                connected=d.connected,
                enabled=d.enabled,
                published_today=stat["published_today"],
                queue_count=stat["queue_count"],
                last_published_at=stat["last_published_at"],
            )
        )

    return result


@app.get(
    "/api/channels/{destination_id}",
    response_model=ChannelDetailResponse,
    dependencies=[Depends(require_admin)],
)
def get_channel_detail_endpoint(
    destination_id: str,
    db: Session = Depends(get_db),
) -> ChannelDetailResponse:
    d = db.get(Destination, destination_id)
    if d is None or d.platform != "youtube":
        raise HTTPException(status_code=404, detail="Không tìm thấy YouTube channel này")

    pipeline = db.get(Pipeline, d.pipeline_id) if d.pipeline_id else None

    sources_data = []
    if pipeline:
        from app.models import DouyinSource
        sources = db.execute(
            select(DouyinSource)
            .where(DouyinSource.pipeline_id == pipeline.id)
            .order_by(DouyinSource.created_at.desc())
        ).scalars().all()
        for s in sources:
            sources_data.append({
                "id": s.id,
                "name": s.name,
                "profile_url": s.profile_url or s.original_profile_url,
                "status": s.inventory_sync_status,
                "video_count": s.inventory_count,
                "last_synced_at": s.last_checked_at.isoformat() if s.last_checked_at else None,
            })

    avatar_url = None
    if d.credentials:
        try:
            c = json.loads(d.credentials)
            avatar_url = c.get("avatar_url")
        except Exception:
            pass

    now_utc = datetime.now(timezone.utc)
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

    published_today = db.execute(
        select(func.count(Publication.id))
        .where(Publication.destination_id == d.id)
        .where(Publication.status == "published")
        .where(Publication.published_at >= today_start)
    ).scalar() or 0

    queue_count = db.execute(
        select(func.count(Publication.id))
        .where(Publication.destination_id == d.id)
        .where(Publication.status.in_(["queued", "pending", "downloading", "ai_metadata", "uploading"]))
    ).scalar() or 0

    last_published_at = db.execute(
        select(func.max(Publication.published_at))
        .where(Publication.destination_id == d.id)
        .where(Publication.status == "published")
    ).scalar()

    channel_item = ChannelItem(
        id=d.id,
        destination_id=d.id,
        pipeline_id=d.pipeline_id,
        pipeline_name=pipeline.name if pipeline else d.pipeline_id,
        channel_id=d.external_account_id,
        channel_title=d.external_account_name or d.name,
        avatar_url=avatar_url,
        connected=d.connected,
        enabled=d.enabled,
        published_today=published_today,
        queue_count=queue_count,
        last_published_at=last_published_at,
    )

    pubs = (
        db.execute(
            select(Publication, DouyinVideo, VideoJob)
            .outerjoin(DouyinVideo, Publication.douyin_video_id == DouyinVideo.id)
            .outerjoin(VideoJob, VideoJob.publication_id == Publication.id)
            .where(Publication.destination_id == d.id)
            .order_by(Publication.created_at.desc())
            .limit(100)
        )
        .all()
    )

    queue_list: list[ManualPublicationItem] = []
    published_list: list[ManualPublicationItem] = []

    for pub, video, job in pubs:
        item = ManualPublicationItem(
            id=pub.id,
            destination_id=pub.destination_id,
            destination_name=d.name,
            platform=pub.platform,
            status=pub.status,
            progress=job.progress if job else (100 if pub.status == "published" else 0),
            video_title=pub.title or (video.title if video else None),
            source_url=video.url if video else None,
            thumbnail=video.thumbnail_url if video else None,
            external_url=pub.external_url,
            error=pub.error or (job.error if job else None),
            created_at=pub.created_at,
            published_at=pub.published_at,
        )
        if pub.status == "published":
            published_list.append(item)
        else:
            queue_list.append(item)

    pipeline_info = {
        "id": pipeline.id if pipeline else "",
        "name": pipeline.name if pipeline else "",
        "slug": pipeline.slug if pipeline else "",
        "enabled": pipeline.enabled if pipeline else False,
        "default_privacy": pipeline.default_privacy if pipeline else "public",
        "daily_upload_limit": pipeline.daily_upload_limit if pipeline else 6,
        "upload_slots": pipeline.upload_slots if pipeline else [],
    }

    inventory_videos = []
    inventory_count = 0
    if pipeline:
        inventory_videos = db.execute(
            select(DouyinVideo)
            .where(DouyinVideo.pipeline_id == pipeline.id)
            .order_by(DouyinVideo.created_at.desc())
            .limit(100)
        ).scalars().all()
        inventory_count = db.execute(
            select(func.count(DouyinVideo.id))
            .where(DouyinVideo.pipeline_id == pipeline.id)
        ).scalar() or 0

    inventory_data = [
        {
            "id": v.id,
            "video_id": v.video_id,
            "title": v.title,
            "description": v.description,
            "thumbnail_url": v.thumbnail_url,
            "url": v.url,
            "status": v.status,
            "is_backlog": v.is_backlog,
            "douyin_created_at": v.douyin_created_at.isoformat() if v.douyin_created_at else None,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in inventory_videos
    ]

    failed_count = db.execute(
        select(func.count(Publication.id))
        .where(Publication.destination_id == d.id)
        .where(Publication.status == "failed")
    ).scalar() or 0

    from app.scheduler import get_next_upload_slot
    slots = d.upload_slots or (pipeline.upload_slots if pipeline else []) or ["08:00", "12:00", "16:00"]
    nxt = get_next_upload_slot(slots, d.timezone or "UTC", now_utc)
    next_slot_str = nxt.isoformat() if nxt else None

    return ChannelDetailResponse(
        channel=channel_item,
        daily_upload_limit=d.daily_upload_limit,
        metadata_profile=d.metadata_profile,
        metadata_language=d.metadata_language,
        fixed_hashtags=d.fixed_hashtags,
        adaptive_hashtags=d.adaptive_hashtags,
        prompt_override=d.prompt_override,
        timezone=d.timezone or "UTC",
        pipeline=pipeline_info,
        sources=sources_data,
        queue=queue_list,
        published=published_list,
        inventory=inventory_data,
        inventory_count=inventory_count,
        failed_count=failed_count,
        next_slot=next_slot_str,
    )


@app.patch(
    "/api/channels/{destination_id}",
    response_model=ChannelDetailResponse,
    dependencies=[Depends(require_admin)],
)
def update_channel_endpoint(
    destination_id: str,
    payload: ChannelUpdateRequest,
    db: Session = Depends(get_db),
) -> ChannelDetailResponse:
    d = db.get(Destination, destination_id)
    if d is None or d.platform != "youtube":
        raise HTTPException(status_code=404, detail="Không tìm thấy YouTube channel này")

    pipeline = db.get(Pipeline, d.pipeline_id) if d.pipeline_id else None

    if payload.name is not None:
        d.name = payload.name
        if pipeline:
            pipeline.name = payload.name
    if payload.daily_upload_limit is not None:
        d.daily_upload_limit = payload.daily_upload_limit
        if pipeline:
            pipeline.daily_upload_limit = payload.daily_upload_limit
    if payload.metadata_profile is not None:
        d.metadata_profile = payload.metadata_profile
        if pipeline:
            pipeline.niche = payload.metadata_profile
    if payload.metadata_language is not None:
        d.metadata_language = payload.metadata_language
        if pipeline:
            pipeline.language = payload.metadata_language
    if payload.fixed_hashtags is not None:
        d.fixed_hashtags = payload.fixed_hashtags
        if pipeline:
            pipeline.fixed_hashtags = payload.fixed_hashtags
    if payload.adaptive_hashtags is not None:
        d.adaptive_hashtags = payload.adaptive_hashtags
        if pipeline:
            pipeline.adaptive_hashtags = payload.adaptive_hashtags
    if payload.prompt_override is not None:
        d.prompt_override = payload.prompt_override
        if pipeline:
            pipeline.prompt_profile = payload.prompt_override
    if payload.timezone is not None:
        d.timezone = payload.timezone
        if pipeline:
            pipeline.timezone = payload.timezone
    if payload.upload_slots is not None:
        d.upload_slots = payload.upload_slots
        if pipeline:
            pipeline.upload_slots = payload.upload_slots
    if payload.enabled is not None:
        d.enabled = payload.enabled
    if payload.default_privacy is not None and pipeline:
        pipeline.default_privacy = payload.default_privacy

    db.commit()
    return get_channel_detail_endpoint(destination_id=destination_id, db=db)


def douyin_quota_can_start() -> bool:
    """True when one more RapidAPI request is allowed above the safety floor."""
    from app import douyin_quota

    try:
        return bool(douyin_quota.can_spend(1))
    except Exception:
        return True


def trigger_inventory_sync_job(source_id: str, mode: str = "full") -> None:
    """Background Douyin discovery runner.

    Manual-inventory mode: discovery only happens because an admin asked for
    it, so this routes to the quota-aware engine instead of the old
    cookie/browser inventory sync.
      * mode='latest'  -> manual refresh (page 1, stop at first known video)
      * anything else  -> initial full import (resumable backlog walk)
    """
    try:
        from app import douyin_import

        if mode == "latest":
            douyin_import.refresh_source(source_id)
        else:
            douyin_import.initial_import(source_id, resume=mode == "resume")
    except Exception:
        logger.exception(
            "Background Douyin discovery failed for source %s", source_id
        )


@app.post(
    "/api/channels/{destination_id}/sources",
    status_code=201,
    dependencies=[Depends(require_admin)],
)
def add_channel_source_endpoint(
    destination_id: str,
    payload: ChannelAddSourceRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    d = db.get(Destination, destination_id)
    if d is None or d.platform != "youtube":
        raise HTTPException(status_code=404, detail="Không tìm thấy YouTube channel này")
    if not d.pipeline_id:
        raise HTTPException(status_code=400, detail="Channel workspace lacks linked pipeline")

    platform = (payload.platform or "douyin").lower()
    name = payload.name.strip()
    url = payload.url.strip()
    if not name or not url:
        raise HTTPException(status_code=400, detail="Vui lòng nhập tên và link tác giả")

    if platform == "facebook":
        from app.models import PipelineSource as _PS
        from app.source_providers import registry as _reg

        prov = _reg.get("facebook")
        resolved = prov.resolve_source(url) if prov else {"source_external_id": url, "source_url": url}
        ps = _PS(
            pipeline_id=d.pipeline_id,
            platform="facebook",
            source_external_id=resolved.get("source_external_id") or url.split("/")[-1].split("?")[0],
            source_url=resolved.get("source_url") or url,
            source_name=name,
            enabled=True,
        )
        db.add(ps)
        db.commit()
        db.refresh(ps)
        return {
            "id": ps.id,
            "name": ps.source_name,
            "profile_url": ps.source_url,
            "status": "idle",
            "video_count": 0,
            "platform": "facebook",
        }

    from app.douyin import parse_profile_url
    parsed = parse_profile_url(url)
    sec_uid = parsed.get("sec_uid")
    clean_url = parsed.get("clean_url") or url

    source = DouyinSource(
        pipeline_id=d.pipeline_id,
        destination_id=d.id,
        name=name,
        profile_url=clean_url,
        original_profile_url=url,
        douyin_sec_uid=sec_uid,
        platform="douyin",
        enabled=True,
        inventory_sync_status="idle",
        scan_interval_minutes=payload.scan_interval_minutes,
        max_videos_per_day=payload.max_videos_per_day,
        start_mode=payload.start_mode,
        initial_limit=payload.initial_limit,
        include_keywords=payload.include_keywords,
        exclude_keywords=payload.exclude_keywords,
        borderline_policy=payload.borderline_policy,
        mismatch_policy=payload.mismatch_policy,
        order=payload.order,
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    # Manual-inventory mode: no automatic scan on creation. The source starts
    # with initial_import_status='pending' and the admin triggers the one-off
    # backlog import (POST /api/sources/{id}/initial-import) so RapidAPI quota
    # is only spent on demand.
    return {
        "id": source.id,
        "name": source.name,
        "profile_url": source.profile_url,
        "status": source.inventory_sync_status,
        "video_count": 0,
        "platform": "douyin",
        "initial_import_status": source.initial_import_status,
        "feed_provider": source.feed_provider,
    }


@app.delete(
    "/api/channels/{destination_id}/sources/{source_id}",
    dependencies=[Depends(require_admin)],
)
def delete_channel_source_endpoint(
    destination_id: str,
    source_id: str,
    db: Session = Depends(get_db),
):
    d = db.get(Destination, destination_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy YouTube channel")

    s = db.get(DouyinSource, source_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy source")

    # Strict isolation check (Requirement 15):
    if s.pipeline_id != d.pipeline_id:
        raise HTTPException(
            status_code=403,
            detail="Cross-workspace mismatch: source does not belong to this channel workspace",
        )

    db.delete(s)
    db.commit()
    return {"ok": True}


@app.post(
    "/api/channels/{destination_id}/sources/{source_id}/sync",
    dependencies=[Depends(require_admin)],
)
def sync_channel_source_endpoint(
    destination_id: str,
    source_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    d = db.get(Destination, destination_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy YouTube channel")

    s = db.get(DouyinSource, source_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy source")

    # Strict isolation check (Requirement 15):
    if s.pipeline_id != d.pipeline_id:
        raise HTTPException(
            status_code=403,
            detail="Cross-workspace mismatch: source does not belong to this channel workspace",
        )

    background_tasks.add_task(trigger_inventory_sync_job, s.id)
    return {"ok": True, "source_id": s.id}


def _require_workspace_source(
    db: Session,
    destination_id: str,
    source_id: str,
) -> tuple[Destination, DouyinSource]:
    d = db.get(Destination, destination_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy YouTube channel")
    s = db.get(DouyinSource, source_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy source")
    if s.pipeline_id != d.pipeline_id:
        raise HTTPException(
            status_code=403,
            detail="Cross-workspace mismatch: source does not belong to this channel workspace",
        )
    return d, s


def _source_with_cookie_out(s: DouyinSource) -> dict:
    # Deprecated per-source cookie fields kept for backwards compat, not used in runtime.
    return {
        "id": s.id,
        "name": s.name,
        "pipeline_id": s.pipeline_id,
        "platform": getattr(s, "platform", "douyin") or "douyin",
        "original_profile_url": s.original_profile_url,
        "profile_url": s.profile_url,
        "source_url": s.profile_url,
        "source_name": s.name,
        "douyin_sec_uid": s.douyin_sec_uid,
        "douyin_user_id": s.douyin_user_id,
        "enabled": s.enabled,
        "inventory_sync_status": s.inventory_sync_status,
        "inventory_count": s.inventory_count,
        "inventory_synced_at": s.inventory_synced_at,
        "inventory_sync_error": s.inventory_sync_error,
        "last_video_id": s.last_video_id,
        "last_checked_at": s.last_checked_at,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
        "cookie_status": "deprecated",
        "cookie_account_name": None,
        "cookie_verified_at": None,
        "needs_reauth": False,
        "scan_interval_minutes": s.scan_interval_minutes or 15,
        "max_videos_per_day": s.max_videos_per_day
        if s.max_videos_per_day is not None else 5,
        "include_keywords": s.include_keywords,
        "exclude_keywords": s.exclude_keywords,
        "next_scan_at": s.next_scan_at,
        "last_scan_at": s.last_scan_at,
        "start_mode": s.start_mode or "new_only",
        "initial_limit": s.initial_limit or 10,
        "baseline_done": bool(s.baseline_done),
        "borderline_policy": s.borderline_policy or "hold",
        "mismatch_policy": s.mismatch_policy or "reject",
        "order": s.order or "oldest_first",
        "cookie_configured": False,
        "status": s.inventory_sync_status,
        "video_count": s.inventory_count,
        # Manual-inventory mode (admin-driven discovery).
        "feed_provider": getattr(s, "feed_provider", "rapidapi_justone"),
        "initial_import_status": getattr(s, "initial_import_status", "pending"),
        "initial_import_cursor": getattr(s, "initial_import_cursor", None),
        "initial_import_pages": int(getattr(s, "initial_import_pages", 0) or 0),
        "initial_import_videos": int(getattr(s, "initial_import_videos", 0) or 0),
        "initial_import_last_error": getattr(s, "initial_import_last_error", None),
        "initial_import_started_at": getattr(s, "initial_import_started_at", None),
        "initial_import_completed_at": getattr(s, "initial_import_completed_at", None),
        "last_refresh_at": getattr(s, "last_refresh_at", None),
        "provider_status": getattr(s, "provider_status", "ok"),
        "provider_status_detail": getattr(s, "provider_status_detail", None),
    }


@app.get(
    "/api/channels/{destination_id}/sources",
    dependencies=[Depends(require_admin)],
)
def list_channel_sources_endpoint(
    destination_id: str,
    db: Session = Depends(get_db),
):
    d = db.get(Destination, destination_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy YouTube channel")
    from app.models import PipelineSource

    douyin = list(
        db.execute(
            select(DouyinSource)
            .where(DouyinSource.pipeline_id == d.pipeline_id)
            .order_by(DouyinSource.created_at.asc())
        ).scalars().all()
    )
    generic = list(
        db.execute(
            select(PipelineSource)
            .where(PipelineSource.pipeline_id == d.pipeline_id)
            .order_by(PipelineSource.created_at.asc())
        ).scalars().all()
    )
    out = [_source_with_cookie_out(s) for s in douyin]
    for g in generic:
        out.append(
            {
                "id": g.id,
                "name": g.source_name,
                "pipeline_id": g.pipeline_id,
                "platform": g.platform,
                "profile_url": g.source_url,
                "source_url": g.source_url,
                "source_name": g.source_name,
                "enabled": g.enabled,
                "inventory_sync_status": "idle",
                "inventory_count": 0,
                "status": "idle",
                "video_count": 0,
                "created_at": g.created_at,
                "updated_at": g.updated_at,
            }
        )
    return out


@app.post(
    "/api/sources/{source_id}/cookie",
    dependencies=[Depends(require_admin)],
)
def save_source_cookie_endpoint(
    source_id: str,
    payload: SourceCookieSave,
    db: Session = Depends(get_db),
):
    from app.source_cookies import save_source_cookie

    s = db.get(DouyinSource, source_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy source")
    try:
        return save_source_cookie(db, s, payload.cookie)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Cookie không hợp lệ: {exc}")


@app.delete(
    "/api/sources/{source_id}/cookie",
    dependencies=[Depends(require_admin)],
)
def delete_source_cookie_endpoint(
    source_id: str,
    db: Session = Depends(get_db),
):
    from app.source_cookies import delete_source_cookie

    s = db.get(DouyinSource, source_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy source")
    return delete_source_cookie(db, s)


@app.post(
    "/api/sources/{source_id}/test",
    dependencies=[Depends(require_admin)],
)
def test_source_cookie_endpoint(
    source_id: str,
    db: Session = Depends(get_db),
):
    from app.source_cookies import test_source_cookie

    s = db.get(DouyinSource, source_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy source")
    try:
        return test_source_cookie(db, s)
    except RuntimeError as exc:
        msg = str(exc)
        code = 410 if msg.startswith("COOKIE_EXPIRED") else 502
        raise HTTPException(status_code=code, detail=msg)


@app.post(
    "/api/sources/{source_id}/scan",
    dependencies=[Depends(require_admin)],
)
def scan_source_now_endpoint(
    source_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    s = db.get(DouyinSource, source_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy source")
    if s.needs_reauth:
        raise HTTPException(
            status_code=409,
            detail="DOUYIN_COOKIE_EXPIRED: cập nhật cookie trước khi scan",
        )
    s.next_scan_at = _utcnow()
    db.commit()
    background_tasks.add_task(trigger_inventory_sync_job, s.id, "latest")
    return {"ok": True, "source_id": s.id}


@app.post(
    "/api/sources/{source_id}/pause",
    dependencies=[Depends(require_admin)],
)
def pause_source_endpoint(
    source_id: str,
    db: Session = Depends(get_db),
):
    s = db.get(DouyinSource, source_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy source")
    s.enabled = False
    db.commit()
    return {"ok": True, "source_id": s.id, "enabled": False}


@app.post(
    "/api/sources/{source_id}/resume",
    dependencies=[Depends(require_admin)],
)
def resume_source_endpoint(
    source_id: str,
    db: Session = Depends(get_db),
):
    s = db.get(DouyinSource, source_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy source")
    if s.needs_reauth:
        raise HTTPException(
            status_code=409,
            detail="DOUYIN_COOKIE_EXPIRED: cập nhật cookie trước khi resume",
        )
    s.enabled = True
    s.next_scan_at = _utcnow()
    db.commit()
    return {"ok": True, "source_id": s.id, "enabled": True}


@app.get(
    "/api/channels/{destination_id}/auto/status",
    dependencies=[Depends(require_admin)],
)
def channel_auto_status_endpoint(
    destination_id: str,
    db: Session = Depends(get_db),
):
    from app.scheduler import count_todays_released_jobs, get_local_day_bounds

    d = db.get(Destination, destination_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy YouTube channel")

    sources = list(
        db.execute(
            select(DouyinSource)
            .where(DouyinSource.pipeline_id == d.pipeline_id)
        ).scalars().all()
    )
    now = _utcnow()
    day_start, _ = get_local_day_bounds(d.timezone or "UTC", now)

    today_published = count_todays_released_jobs(
        db,
        db.get(Pipeline, d.pipeline_id),
        day_start,
        d,
    ) if d.pipeline_id else 0

    queue_count = db.execute(
        select(func.count(Publication.id))
        .where(Publication.destination_id == d.id)
        .where(Publication.status.in_(
            ["queued", "scheduled", "pending", "downloading", "uploading", "ai_metadata"]
        ))
    ).scalar_one_or_none() or 0
    failed_count = db.execute(
        select(func.count(Publication.id))
        .where(Publication.destination_id == d.id)
        .where(Publication.status == "failed")
    ).scalar_one_or_none() or 0

    pipe_id = d.pipeline_id
    held_count = db.execute(
        select(func.count(DouyinVideo.id))
        .where(DouyinVideo.pipeline_id == pipe_id)
        .where(DouyinVideo.status == "held")
    ).scalar_one_or_none() or 0 if pipe_id else 0
    rejected_count = db.execute(
        select(func.count(DouyinVideo.id))
        .where(DouyinVideo.pipeline_id == pipe_id)
        .where(DouyinVideo.status == "rejected")
    ).scalar_one_or_none() or 0 if pipe_id else 0

    scans = [s.last_scan_at for s in sources if s.last_scan_at]
    nexts = [s.next_scan_at for s in sources if s.next_scan_at and s.enabled and not s.needs_reauth]

    return {
        "auto_enabled": bool(d.enabled),
        "sources_count": len(sources),
        "enabled_sources": len([s for s in sources if s.enabled]),
        "needs_reauth_sources": len([s for s in sources if s.needs_reauth]),
        "last_scan_at": max(scans).isoformat() if scans else None,
        "next_scan_at": min(nexts).isoformat() if nexts else None,
        "today_published": int(today_published or 0),
        "today_limit": int(d.daily_upload_limit or 0),
        "queue_count": int(queue_count),
        "failed_count": int(failed_count),
        "held_count": int(held_count),
        "rejected_count": int(rejected_count),
    }


# ── Global Platform Accounts (shared login) ──
@app.get(
    "/api/platform-accounts",
    dependencies=[Depends(require_admin)],
)
def list_platform_accounts_endpoint(db: Session = Depends(get_db)):
    from app.models import PlatformAccount

    accounts = list(db.execute(select(PlatformAccount).order_by(PlatformAccount.platform.asc())).scalars().all())
    # Ensure douyin/facebook rows exist for UI
    for plat in ("douyin", "facebook"):
        if not any(a.platform == plat for a in accounts):
            accounts.append(
                PlatformAccount(platform=plat, display_name=plat.capitalize(), status="needs_login")  # type: ignore
            )
    result = []
    for acct in accounts:
        # Count how many sources use this platform (across all pipelines)
        used_by = 0
        try:
            used_by = db.execute(select(func.count(DouyinSource.id)).where(DouyinSource.platform == acct.platform)).scalar_one_or_none() or 0
        except Exception:
            used_by = 0
        result.append(
            {
                "platform": acct.platform,
                "display_name": acct.display_name,
                "status": acct.status,
                "connected": acct.status == "connected",
                "last_verified_at": acct.last_verified_at.isoformat() if getattr(acct, "last_verified_at", None) else None,
                "last_error": getattr(acct, "last_error", None),
                "used_by_sources": int(used_by),
            }
        )
    return result


@app.post(
    "/api/platform-accounts/douyin",
    dependencies=[Depends(require_admin)],
)
def save_douyin_platform_account_endpoint(
    payload: SourceCookieSave,
    db: Session = Depends(get_db),
):
    from app.platform_accounts import save_platform_credentials

    try:
        acct = save_platform_credentials(db, "douyin", payload.cookie)
        return {
            "platform": acct.platform,
            "status": acct.status,
            "connected": acct.status == "connected",
            "last_verified_at": acct.last_verified_at.isoformat() if acct.last_verified_at else None,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Cookie không hợp lệ: {exc}")


@app.post(
    "/api/platform-accounts/douyin/test",
    dependencies=[Depends(require_admin)],
)
def test_douyin_platform_account_endpoint(db: Session = Depends(get_db)):
    from app.platform_accounts import test_platform_account

    try:
        return test_platform_account(db, "douyin")
    except RuntimeError as exc:
        msg = str(exc)
        code = 410 if "COOKIE_EXPIRED" in msg else 502
        raise HTTPException(status_code=code, detail=msg)


@app.delete(
    "/api/platform-accounts/douyin",
    dependencies=[Depends(require_admin)],
)
def delete_douyin_platform_account_endpoint(db: Session = Depends(get_db)):
    from app.models import PlatformAccount

    acct = db.execute(select(PlatformAccount).where(PlatformAccount.platform == "douyin").limit(1)).scalar_one_or_none()
    if acct is None:
        return {"ok": True}
    acct.credentials_encrypted = None
    acct.status = "needs_login"
    acct.last_verified_at = None
    acct.last_error = None
    db.commit()
    return {"ok": True, "platform": "douyin", "status": "needs_login"}


@app.post(
    "/api/platform-accounts/facebook",
    dependencies=[Depends(require_admin)],
)
def save_facebook_platform_account_endpoint(
    payload: SourceCookieSave,
    db: Session = Depends(get_db),
):
    from app.platform_accounts import save_platform_credentials

    try:
        acct = save_platform_credentials(db, "facebook", payload.cookie, display_name="Facebook")
        return {"platform": acct.platform, "status": acct.status, "connected": acct.status == "connected"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete(
    "/api/platform-accounts/facebook",
    dependencies=[Depends(require_admin)],
)
def delete_facebook_platform_account_endpoint(db: Session = Depends(get_db)):
    from app.models import PlatformAccount

    acct = db.execute(select(PlatformAccount).where(PlatformAccount.platform == "facebook").limit(1)).scalar_one_or_none()
    if acct is None:
        return {"ok": True}
    acct.credentials_encrypted = None
    acct.status = "needs_login"
    acct.last_verified_at = None
    db.commit()
    return {"ok": True}



@app.patch(
    "/api/pipeline-sources/{source_id}",
    dependencies=[Depends(require_admin)],
)
def update_pipeline_source_endpoint(
    source_id: str,
    payload: dict,
    db: Session = Depends(get_db),
):
    from app.models import PipelineSource

    src = db.get(PipelineSource, source_id)
    if src is None:
        # Fallback to DouyinSource for legacy
        src2 = db.get(DouyinSource, source_id)
        if src2 is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy source")
        # Allow toggling enabled via legacy table
        if "enabled" in payload:
            src2.enabled = bool(payload["enabled"])
            db.commit()
        return {"ok": True, "id": src2.id, "enabled": src2.enabled}
    if "enabled" in payload:
        src.enabled = bool(payload["enabled"])
    if "priority" in payload:
        src.priority = int(payload["priority"])
    db.commit()
    return {"ok": True, "id": src.id, "enabled": src.enabled}


@app.delete(
    "/api/pipeline-sources/{source_id}",
    dependencies=[Depends(require_admin)],
)
def delete_pipeline_source_endpoint(
    source_id: str,
    db: Session = Depends(get_db),
):
    from app.models import PipelineSource

    src = db.get(PipelineSource, source_id)
    if src is not None:
        db.delete(src)
        db.commit()
        return {"ok": True}
    # Fallback legacy
    dsrc = db.get(DouyinSource, source_id)
    if dsrc is not None:
        db.delete(dsrc)
        db.commit()
        return {"ok": True}
    raise HTTPException(status_code=404, detail="Không tìm thấy source")


@app.post(
    "/api/pipeline-sources/{source_id}/scan",
    dependencies=[Depends(require_admin)],
)
def scan_pipeline_source_endpoint(
    source_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    from app.models import PipelineSource

    src = db.get(PipelineSource, source_id)
    if src is not None:
        # For Facebook stub, just return
        if src.platform != "douyin":
            return {"ok": True, "platform": src.platform, "note": "Facebook scan queued (stub)"}
        # For pipeline_sources douyin, we need a DouyinSource-like sync
        # For now, return ok (real Douyin pipeline_sources not yet scanned via Playwright)
        return {"ok": True, "source_id": src.id}
    # Legacy DouyinSource
    ds = db.get(DouyinSource, source_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy source")
    if getattr(ds, "needs_reauth", False):
        # Check global account instead
        from app.models import PlatformAccount

        acct = db.execute(select(PlatformAccount).where(PlatformAccount.platform == "douyin").limit(1)).scalar_one_or_none()
        if acct is None or acct.status != "connected":
            raise HTTPException(status_code=409, detail="Douyin PlatformAccount needs login (global)")
    ds.next_scan_at = _utcnow()
    db.commit()
    background_tasks.add_task(trigger_inventory_sync_job, ds.id, "latest")
    return {"ok": True, "source_id": ds.id}


@app.get(
    "/api/channels/{destination_id}/inventory",
    dependencies=[Depends(require_admin)],
)
def get_channel_inventory_endpoint(
    destination_id: str,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    d = db.get(Destination, destination_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy YouTube channel")

    if not d.pipeline_id:
        return {"items": [], "total": 0}

    query = select(DouyinVideo).where(DouyinVideo.pipeline_id == d.pipeline_id)
    total_query = select(func.count(DouyinVideo.id)).where(DouyinVideo.pipeline_id == d.pipeline_id)

    if status and status != "all":
        query = query.where(DouyinVideo.status == status)
        total_query = total_query.where(DouyinVideo.status == status)

    total = db.execute(total_query).scalar() or 0
    videos = db.execute(
        query.order_by(DouyinVideo.created_at.desc()).offset(offset).limit(limit)
    ).scalars().all()

    return {
        "total": total,
        "items": [
            {
                "id": v.id,
                "video_id": v.video_id,
                "title": v.title,
                "description": v.description,
                "thumbnail_url": v.thumbnail_url,
                "url": v.url,
                "status": v.status,
                "is_backlog": v.is_backlog,
                "douyin_created_at": v.douyin_created_at.isoformat() if v.douyin_created_at else None,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in videos
        ],
    }


@app.post(
    "/api/channels/{destination_id}/publish",
    response_model=ManualPublishResponse,
    status_code=202,
    dependencies=[Depends(require_admin)],
)
def channel_workspace_publish_endpoint(
    destination_id: str,
    payload: ManualPublishRequest,
    db: Session = Depends(get_db),
) -> ManualPublishResponse:
    d = db.get(Destination, destination_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy YouTube channel")

    # Force destination to this channel workspace only
    payload.destination_ids = [d.id]
    return manual_publish_endpoint(payload=payload, db=db)

