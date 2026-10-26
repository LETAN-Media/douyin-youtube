from fastapi import APIRouter, Depends

from ..dependencies import require_admin
from ..services.dashboard_cache import get_cached, invalidate

router = APIRouter(prefix="/api/tiktok/flow", tags=["flow"])


@router.get("/pipeline/{pipeline_id}", dependencies=[Depends(require_admin)])
async def pipeline_flow(pipeline_id: str):
    """Aggregate pipeline → sources → reel counts with caching."""

    async def _load():
        from ..db.repositories import pipelines as pipelines_repo
        from ..db.repositories import reels as reels_repo
        from ..db.repositories import sources as sources_repo
        from ..db.repositories import scan_runs as scan_runs_repo
        from ..db.repositories import publications as publications_repo
        from ..db.repositories import destinations
        from ..db.client import execute

        pipeline = await pipelines_repo.get_pipeline(pipeline_id)
        if pipeline is None:
            return {"error": "pipeline not found"}

        src_rows = await sources_repo.list_sources(pipeline_id)
        dest_rows = await destinations.list_destinations(pipeline_id)

        sources_data = []
        total_reels = 0
        total_unpublished = 0
        total_published = 0
        for src in src_rows:
            total = await reels_repo.count_reels(src["id"])
            unpublished = await reels_repo.count_unpublished(src["id"])
            published = await reels_repo.count_published(src["id"])
            total_reels += total
            total_unpublished += unpublished
            total_published += published

            # last scan run
            res = await execute(
                "SELECT id, status, discovered_count, inserted_count, "
                "started_at, completed_at FROM tiktok_scan_runs "
                "WHERE source_id = :sid ORDER BY started_at DESC LIMIT 1",
                {"sid": src["id"]},
            )
            last_scan = dict(res.rows[0]) if res.rows else None

            # pending publications
            pub_res = await execute(
                "SELECT COUNT(*) as cnt FROM tiktok_publications WHERE reel_db_id IN "
                "(SELECT id FROM tiktok_reels WHERE source_id = :sid) "
                "AND status IN ('queued','processing')",
                {"sid": src["id"]},
            )
            pending_pubs = pub_res.rows[0][0] if pub_res.rows else 0

            sources_data.append({
                "id": src["id"],
                "username": src["username"],
                "display_name": src["display_name"],
                "enabled": src["enabled"],
                "initial_scan_completed": src["initial_scan_completed"],
                "discovered_total": src["discovered_total"],
                "last_scan": last_scan,
                "total_reels": total,
                "unpublished": unpublished,
                "published": published,
                "pending_pubs": pending_pubs,
            })

        # queue count
        qres = await execute(
            "SELECT COUNT(*) as cnt FROM tiktok_publish_queue WHERE status = 'queued'"
        )
        queue_count = qres.rows[0][0] if qres.rows else 0

        return {
            "pipeline": pipeline,
            "destinations": dest_rows,
            "sources": sources_data,
            "summary": {
                "total_sources": len(src_rows),
                "total_destinations": len(dest_rows),
                "total_reels": total_reels,
                "unpublished": total_unpublished,
                "published": total_published,
                "queue_count": queue_count,
            },
        }

    return await get_cached(f"pipeline:{pipeline_id}:flow", _load)


@router.get("/invalidate/{pipeline_id}", dependencies=[Depends(require_admin)])
async def invalidate_cache(pipeline_id: str):
    invalidate(f"pipeline:{pipeline_id}:flow")
    return {"status": "cache invalidated"}
