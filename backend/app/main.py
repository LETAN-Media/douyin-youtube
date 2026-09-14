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
    DestinationCreate,
    DestinationOut,
    DestinationUpdate,
    DouyinSourceCreate,
    DouyinSourceOut,
    DouyinSourceUpdate,
    DouyinVideoOut,
    DouyinVideoWithPublications,
    InventoryListResponse,
    JobCreate,
    JobOut,
    PipelineCreate,
    PipelineOut,
    PipelineUpdate,
    PublicationOut,
    PublicationPublishRequest,
    PublicationRescheduleRequest,
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
    response_model=list[DouyinSourceOut],
    dependencies=[
        Depends(require_admin)
    ],
)
def list_pipeline_sources(
    pipeline_id: str,
    db: Session = Depends(
        get_db
    ),
) -> list[DouyinSource]:
    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy pipeline",
        )

    return list(
        db.execute(
            select(DouyinSource)
            .where(DouyinSource.pipeline_id == pipeline_id)
            .order_by(DouyinSource.created_at.asc())
        )
        .scalars()
        .all()
    )


@app.post(
    "/api/pipelines/{pipeline_id}/sources",
    response_model=DouyinSourceOut,
    status_code=201,
    dependencies=[
        Depends(require_admin)
    ],
)
def create_pipeline_source(
    pipeline_id: str,
    payload: DouyinSourceCreate,
    db: Session = Depends(
        get_db
    ),
) -> DouyinSource:
    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy pipeline",
        )

    profile_url = payload.profile_url
    douyin_sec_uid = payload.douyin_sec_uid
    original_profile_url = profile_url

    if profile_url and not douyin_sec_uid:
        parsed = parse_douyin_profile_url(profile_url)
        if parsed:
            douyin_sec_uid = parsed.sec_uid
            profile_url = parsed.canonical

    source = DouyinSource(
        pipeline_id=pipeline_id,
        name=payload.name,
        original_profile_url=original_profile_url,
        profile_url=profile_url,
        douyin_sec_uid=douyin_sec_uid or payload.douyin_sec_uid,
        douyin_user_id=payload.douyin_user_id,
        enabled=payload.enabled,
        inventory_sync_status="queued",
        inventory_count=0,
        inventory_sync_error=None,
    )

    db.add(source)
    db.commit()
    db.refresh(source)

    # Initial full background inventory sync (queued -> running ->
    # completed/auth_required/failed). sync_source_inventory owns the
    # terminal status; never overwrite auth_required/failed with completed.
    try:
        from app.inventory import sync_source_inventory
        sync_source_inventory(source.id, mode="full")
        db.refresh(source)
    except Exception:
        logger.exception("Background inventory sync failed for source %s", source.id)
        try:
            source.inventory_sync_status = "failed"
            db.commit()
            db.refresh(source)
        except Exception:
            pass

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

    next_upload = None
    if destination.upload_slots:
        slot_times = []
        for slot_str in destination.upload_slots:
            try:
                hour, minute = map(int, slot_str.split(":"))
                slot_time = datetime.combine(
                    datetime.now().date(),
                    datetime.min.time().replace(hour=hour, minute=minute),
                )
                if slot_time.tzinfo is None:
                    slot_time = slot_time.replace(tzinfo=timezone.utc)
                slot_times.append(slot_time)
            except ValueError:
                continue

        future_slots = [s for s in slot_times if s >= datetime.now(timezone.utc)]
        if future_slots:
            next_upload = min(future_slots).isoformat()
        elif slot_times:
            tomorrow = datetime.now().date() + timedelta(days=1)
            hour, minute = map(int, destination.upload_slots[0].split(":"))
            slot_time = datetime.combine(
                tomorrow,
                datetime.min.time().replace(hour=hour, minute=minute),
            )
            if slot_time.tzinfo is None:
                slot_time = slot_time.replace(tzinfo=timezone.utc)
            next_upload = slot_time.isoformat()

    return {
        "connected": destination.connected,
        "platform": destination.platform,
        "name": destination.name,
        "daily_upload_limit": destination.daily_upload_limit,
        "today_published": today_published,
        "next_upload": next_upload,
        "enabled": destination.enabled,
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
                    f"/destinations/{destination.id}?oauth=success"
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
    db.commit()
    db.refresh(publication)

    return publication


@app.post(
    "/api/sources/{source_id}/sync",
    response_model=SourceSyncResponse,
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
    source = db.get(DouyinSource, source_id)
    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy source",
        )

    source.inventory_sync_status = "running"
    source.inventory_sync_error = None
    db.commit()

    try:
        from app.inventory import sync_source_inventory

        result = sync_source_inventory(source.id, mode="full")
        db.refresh(source)
        return SourceSyncResponse(
            source_id=source.id,
            status=source.inventory_sync_status or "completed",
            new=int(result.get("new", 0)),
            updated=int(result.get("updated", 0)),
        )
    except Exception as exc:
        logger.exception("Manual inventory sync failed for source %s", source.id)
        try:
            source.inventory_sync_status = "failed"
            db.commit()
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"Sync thất bại: {exc}",
        ) from exc


@app.post(
    "/api/pipelines/{pipeline_id}/sync",
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

    from app.inventory import sync_source_inventory

    total_new = 0
    total_updated = 0
    for source in sources:
        try:
            result = sync_source_inventory(source.id, mode="full")
            total_new += int(result.get("new", 0))
            total_updated += int(result.get("updated", 0))
        except Exception:
            logger.exception("Pipeline sync failed for source %s", source.id)

    return {"new": total_new, "updated": total_updated}


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
