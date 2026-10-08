"""Pipeline processing settings + series job routes."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import require_admin
from ..db.repositories import drama as repo
from ..db.repositories import processing as proc
from ._common import _err

router = APIRouter(prefix="/api/drama", tags=["drama-processing"])


class ProcessingSettingsUpdate(BaseModel):
    processing_mode: str = "direct_merge"
    merge_all_episodes: bool = True
    episodes_per_video: int | None = None
    target_language: str | None = None
    subtitle_enabled: bool = True
    tts_enabled: bool = False
    template_enabled: bool = False
    template_id: str | None = None
    template_mode: str | None = None
    youtube_destination_id: str | None = None
    auto_publish: bool = True


@router.get("/pipelines/{pipeline_id}/processing-settings")
async def get_processing_settings(
    pipeline_id: str, _: None = Depends(require_admin)
) -> dict:
    if repo.get_pipeline(pipeline_id) is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found.")
    settings = proc.get_settings(pipeline_id)
    _, total = _series_episode_total(pipeline_id)
    chunks = proc.plan_chunks(total, settings)
    return {**settings, "total_episodes": total, "planned_videos": len(chunks)}


def _series_episode_total(pipeline_id: str) -> tuple[list[dict], int]:
    from ..db.client import get_client

    conn = get_client()
    total = conn.execute(
        "SELECT COUNT(*) FROM drama_episodes r "
        "JOIN drama_series t ON t.id = r.series_id "
        "JOIN drama_sources s ON s.id = t.source_id "
        "WHERE s.pipeline_id = ?",
        (pipeline_id,),
    ).fetchone()[0]
    return [], total


@router.put("/pipelines/{pipeline_id}/processing-settings")
async def update_processing_settings(
    pipeline_id: str, body: ProcessingSettingsUpdate,
    _: None = Depends(require_admin),
) -> dict:
    if repo.get_pipeline(pipeline_id) is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found.")
    if body.template_id:
        from ..db.repositories import templates as templates_repo

        if templates_repo.get_template(body.template_id.strip()) is None:
            raise _err(404, "TEMPLATE_NOT_FOUND", "Template not found.")
    try:
        settings = proc.update_settings(
            pipeline_id,
            processing_mode=body.processing_mode,
            merge_all_episodes=body.merge_all_episodes,
            episodes_per_video=body.episodes_per_video,
            target_language=body.target_language,
            subtitle_enabled=body.subtitle_enabled,
            tts_enabled=body.tts_enabled,
            template_enabled=body.template_enabled,
            template_id=body.template_id,
            template_mode=body.template_mode,
            youtube_destination_id=body.youtube_destination_id,
            auto_publish=body.auto_publish,
        )
    except ValueError as exc:
        raise _err(400, "INVALID_SETTINGS", str(exc))
    _, total = _series_episode_total(pipeline_id)
    chunks = proc.plan_chunks(total, settings)
    return {**settings, "total_episodes": total, "planned_videos": len(chunks)}


@router.get("/series/{series_id}/jobs")
async def list_series_jobs(
    series_id: str, _: None = Depends(require_admin)
) -> dict:
    if repo.get_series(series_id) is None:
        raise _err(404, "SERIES_NOT_FOUND", "Series not found.")
    return {"items": proc.list_jobs(series_id)}


@router.post("/series/{series_id}/jobs", status_code=201)
async def create_series_jobs(
    series_id: str, _: None = Depends(require_admin)
) -> dict:
    """Plan chunk jobs for a series from its pipeline settings."""
    series = repo.get_series(series_id)
    if series is None:
        raise _err(404, "SERIES_NOT_FOUND", "Series not found.")
    source = repo.get_source(series["source_id"])
    if source is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Owning source not found.")
    pipeline_id = source["pipeline_id"]
    settings = proc.get_settings(pipeline_id)
    total = repo.list_episodes(series_id, limit=1)[1]
    chunks = proc.plan_chunks(total, settings)
    if not chunks:
        raise _err(400, "NO_EPISODES", "Series has no episodes to process.")
    jobs = [
        proc.create_job(
            pipeline_id, series_id, settings["processing_mode"], idx,
            start, end,
        )
        for idx, (start, end) in enumerate(chunks)
    ]
    return {"items": jobs}


@router.get("/pipelines/{pipeline_id}/jobs")
async def list_pipeline_jobs(
    pipeline_id: str, limit: int = 50, _: None = Depends(require_admin)
) -> dict:
    if repo.get_pipeline(pipeline_id) is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found.")
    return {"items": proc.list_pipeline_jobs(pipeline_id, limit=limit)}


class RetryBody(BaseModel):
    episode_numbers: list[int] | None = None
    failed_only: bool = False


@router.get("/series-jobs/{job_id}/episodes")
async def list_job_episodes(
    job_id: str, _: None = Depends(require_admin)
) -> dict:
    from ..db.repositories import episode_tasks as tasks_repo

    job = proc.get_job(job_id)
    if job is None:
        raise _err(404, "JOB_NOT_FOUND", "Job not found.")
    tasks = tasks_repo.list_tasks(job_id)
    return {"items": tasks, "counts": tasks_repo.count_by_status(job_id)}


@router.post("/series-jobs/{job_id}/retry")
async def retry_job_episodes(
    job_id: str, body: RetryBody, _: None = Depends(require_admin)
) -> dict:
    from ..db.repositories import episode_tasks as tasks_repo

    job = proc.get_job(job_id)
    if job is None:
        raise _err(404, "JOB_NOT_FOUND", "Job not found.")
    if body.episode_numbers:
        tasks = tasks_repo.list_tasks(job_id)
        wanted = set(body.episode_numbers)
        episode_ids = [t["episode_id"] for t in tasks if t["episode_number"] in wanted]
        if not episode_ids:
            raise _err(404, "EPISODES_NOT_FOUND", "No matching episodes in this job.")
        reset = tasks_repo.reset_tasks(job_id, episode_ids)
    elif body.failed_only:
        reset = tasks_repo.reset_tasks(job_id, only_failed=True)
    else:
        raise _err(400, "NOTHING_TO_RETRY", "Provide episode_numbers or failed_only=true.")
    proc.update_job(job_id, status="queued", stage="queued")
    return {"ok": True, "job_id": job_id, "reset": reset}
