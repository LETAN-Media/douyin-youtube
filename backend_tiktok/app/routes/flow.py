from fastapi import APIRouter, Depends

from ..dependencies import require_admin
from ..services.dashboard_cache import get_cached, invalidate

router = APIRouter(prefix="/api/tiktok/flow", tags=["flow"])


@router.get("/pipeline/{pipeline_id}", dependencies=[Depends(require_admin)])
async def pipeline_flow(pipeline_id: str):
    """Aggregate pipeline → sources → reel counts with caching and flow steps."""

    async def _load():
        from ..db.repositories import pipelines as pipelines_repo
        from ..db.repositories import reels as reels_repo
        from ..db.repositories import sources as sources_repo
        from ..db.repositories import scan_runs as scan_runs_repo
        from ..db.repositories import publications as publications_repo
        from ..db.repositories import destinations
        from ..db.client import execute, result_to_dict

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
            last_scan = result_to_dict(res)

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

        # Queue and processing count for this pipeline
        qres = await execute(
            """
            SELECT
                SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) AS queued_cnt,
                SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) AS proc_cnt
            FROM tiktok_publish_queue
            WHERE pipeline_id = :pid
            """,
            {"pid": pipeline_id},
        )
        queue_count = (qres.rows[0][0] or 0) if qres.rows else 0
        processing_count = (qres.rows[0][1] or 0) if qres.rows else 0

        # AI metadata prepared count
        ai_res = await execute(
            """
            SELECT COUNT(*) FROM tiktok_ai_metadata m
            JOIN tiktok_reels r ON r.id = m.reel_db_id
            JOIN tiktok_sources s ON s.id = r.source_id
            WHERE s.pipeline_id = :pid AND m.status = 'completed'
            """,
            {"pid": pipeline_id},
        )
        ai_prepared_count = ai_res.rows[0][0] if ai_res.rows else 0

        # Scheduled publication count
        sched_res = await execute(
            """
            SELECT COUNT(*) FROM tiktok_publications pub
            JOIN youtube_destinations d ON d.id = pub.destination_id
            WHERE d.pipeline_id = :pid AND pub.status IN ('queued', 'scheduled')
            """,
            {"pid": pipeline_id},
        )
        scheduled_count = sched_res.rows[0][0] if sched_res.rows else 0

        # Schedule record
        from ..db.repositories import schedules as schedules_repo
        sched_row = await schedules_repo.get_by_pipeline(pipeline_id)
        sched_enabled = bool(sched_row.get("enabled")) if sched_row else False

        # Connected destinations
        connected_dest_list = [d for d in dest_rows if bool(d.get("connected")) and bool(d.get("enabled", 1))]
        connected_dest_count = len(connected_dest_list)

        # Step 1: Source status
        if not src_rows:
            source_status = "not_configured"
            source_detail = "Chưa có nguồn TikTok"
        elif any((s.get("last_scan") or {}).get("status") == "running" for s in sources_data):
            source_status = "running"
            source_detail = "Đang quét video TikTok..."
        elif any((s.get("last_scan") or {}).get("status") == "failed" for s in sources_data):
            source_status = "error"
            source_detail = "Quét gần nhất thất bại"
        else:
            source_status = "ready"
            source_detail = f"{len(src_rows)} nguồn · {total_reels} video"

        # Step 2: Inventory status
        if total_reels == 0:
            inventory_status = "idle"
            inventory_detail = "Chưa có video trong kho"
        elif total_unpublished > 0:
            inventory_status = "ready"
            inventory_detail = f"{total_unpublished} video chưa đăng"
        else:
            inventory_status = "done"
            inventory_detail = f"{total_published} video đã đăng"

        # Step 3: AI Metadata status
        if ai_prepared_count > 0:
            ai_status = "ready"
            ai_detail = f"{ai_prepared_count} video đã có AI metadata"
        elif total_unpublished > 0:
            ai_status = "ready"
            ai_detail = f"{total_unpublished} video sẵn sàng tạo SEO"
        else:
            ai_status = "idle"
            ai_detail = "Đang chờ video mới"

        # Step 4: Scheduler status
        is_auto = bool(pipeline.get("auto_publish", False))
        if not is_auto:
            scheduler_status = "idle"
            scheduler_detail = "Auto OFF (Chế độ thủ công)"
        elif not sched_enabled:
            scheduler_status = "not_configured"
            scheduler_detail = "Lịch đăng tự động chưa bật"
        elif connected_dest_count == 0:
            scheduler_status = "waiting"
            scheduler_detail = "Chờ kết nối YouTube Destination"
        else:
            scheduler_status = "ready"
            scheduler_detail = f"Auto ON · {scheduled_count} video đã lên lịch"

        # Step 5: Publisher status
        if processing_count > 0:
            publisher_status = "running"
            publisher_detail = f"Đang đăng {processing_count} video lên YouTube..."
        elif queue_count > 0:
            publisher_status = "waiting"
            publisher_detail = f"{queue_count} video trong hàng đợi"
        elif total_published > 0:
            publisher_status = "done"
            publisher_detail = f"{total_published} video đã đăng"
        else:
            publisher_status = "idle"
            publisher_detail = "Publisher đang chờ việc (Idle)"

        # Step 6: YouTube Destination status
        if not dest_rows:
            destination_status = "not_configured"
            destination_detail = "Chưa thêm kênh YouTube"
        elif connected_dest_count > 0:
            primary = connected_dest_list[0]
            destination_status = "ready"
            destination_detail = f"{connected_dest_count} kênh kết nối ({primary.get('channel_name') or 'YouTube'})"
        else:
            destination_status = "waiting"
            destination_detail = "Chưa kết nối OAuth YouTube"

        active_edges = []
        if source_status == "running":
            active_edges.append("source->inventory")
        if total_unpublished > 0 and (ai_status == "ready" or scheduler_status == "ready"):
            active_edges.append("inventory->ai_metadata")
        if sched_enabled and (queue_count > 0 or scheduled_count > 0):
            active_edges.append("ai_metadata->scheduler")
        if queue_count > 0:
            active_edges.append("scheduler->publisher")
        if publisher_status == "running":
            active_edges.append("publisher->youtube_destination")

        return {
            "pipeline": pipeline,
            "pipeline_id": pipeline_id,
            "pipeline_name": pipeline.get("name", ""),
            "live": bool(pipeline.get("enabled", True)),
            "auto_publish": is_auto,
            "destinations": dest_rows,
            "sources": sources_data,
            "sources_count": len(src_rows),
            "inventory_count": total_reels,
            "published_count": total_published,
            "queued_count": queue_count,
            "steps": {
                "source": source_status,
                "inventory": inventory_status,
                "ai_metadata": ai_status,
                "scheduler": scheduler_status,
                "publisher": publisher_status,
                "youtube_destination": destination_status,
            },
            "details": {
                "source": source_detail,
                "inventory": inventory_detail,
                "ai_metadata": ai_detail,
                "scheduler": scheduler_detail,
                "publisher": publisher_detail,
                "youtube_destination": destination_detail,
            },
            "active_edges": active_edges,
            "summary": {
                "total_sources": len(src_rows),
                "total_destinations": len(dest_rows),
                "connected_destinations": connected_dest_count,
                "total_reels": total_reels,
                "unpublished": total_unpublished,
                "published": total_published,
                "queue_count": queue_count,
                "processing_count": processing_count,
                "scheduled_count": scheduled_count,
                "ai_prepared_count": ai_prepared_count,
            },
        }

    return await get_cached(f"pipeline:{pipeline_id}:flow", _load)


@router.get("/invalidate/{pipeline_id}", dependencies=[Depends(require_admin)])
async def invalidate_cache(pipeline_id: str):
    invalidate(f"pipeline:{pipeline_id}:flow")
    return {"status": "cache invalidated"}
