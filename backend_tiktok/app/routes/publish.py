from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import require_admin
from ..db.repositories import destinations, pipelines, reels, scan_runs
from ..db.repositories import publications as publications_repo
from ..db.repositories import publish_queue
from ..db.repositories import schedules

router = APIRouter(prefix="/api/tiktok/publish", tags=["publish"])


@router.post("/pipeline/{pipeline_id}", dependencies=[Depends(require_admin)])
async def publish_pipeline(pipeline_id: str, body: dict):
    """Queue a reel for publishing to YouTube."""
    destination_id = body.get("destination_id")
    reel_db_id = body.get("reel_db_id")
    if not destination_id or not reel_db_id:
        raise HTTPException(status_code=400, detail="destination_id and reel_db_id required")

    import secrets as _secrets

    pub_id = f"pub_{_secrets.token_hex(8)}"
    pub = await publications_repo.create_publication(
        publication_id=pub_id,
        reel_db_id=reel_db_id,
        destination_id=destination_id,
        status="queued",
    )

    job_id = f"job_{_secrets.token_hex(8)}"
    await publish_queue.enqueue_publication_job(
        job_id=job_id,
        pipeline_id=pipeline_id,
        destination_id=destination_id,
        reel_db_id=reel_db_id,
        publication_id=pub_id,
        priority=body.get("priority", 0),
    )
    return {"publication_id": pub_id, "job_id": job_id, "status": "queued"}


@router.get("/jobs", dependencies=[Depends(require_admin)])
async def list_queue(status: str | None = None, limit: int = 50):
    from ..db.client import execute

    where = ""
    params: dict = {"limit": limit}
    if status:
        where = "WHERE status = :status"
        params["status"] = status
    res = await execute(
        f"SELECT id, pipeline_id, destination_id, reel_db_id, publication_id, "
        f"status, priority, stage, error_code, error, queued_at, started_at, finished_at "
        f"FROM tiktok_publish_queue {where} ORDER BY queued_at DESC LIMIT :limit",
        params,
    )
    return [dict(r) for r in res.rows]


@router.get("/publications/{destination_id}", dependencies=[Depends(require_admin)])
async def list_publications(destination_id: str):
    return await publications_repo.list_publications(destination_id)


@router.get("/publication/{publication_id}", dependencies=[Depends(require_admin)])
async def get_publication_route(publication_id: str):
    pub = await publications_repo.get_publication(publication_id)
    if pub is None:
        raise HTTPException(status_code=404, detail="Publication not found")
    return pub


@router.get("/destinations/pipeline/{pipeline_id}", dependencies=[Depends(require_admin)])
async def list_destinations(pipeline_id: str):
    return await destinations.list_destinations(pipeline_id)


@router.post("/destinations", dependencies=[Depends(require_admin)])
async def create_destination(body: dict):
    import secrets as _secrets

    dest_id = body.get("id") or f"dest_{_secrets.token_hex(8)}"
    return await destinations.create_destination(
        destination_id=dest_id,
        pipeline_id=body["pipeline_id"],
        channel_id=body.get("channel_id"),
        channel_name=body.get("channel_name"),
        account_id=body.get("account_id"),
        visibility=body.get("visibility", "public"),
    )
