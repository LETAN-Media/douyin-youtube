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
        from ..db.repositories import system_state
        from ..db.client import execute, result_to_dict

        pipeline = await pipelines_repo.get_pipeline(pipeline_id)
        if pipeline is None:
            return {"error": "pipeline not found"}

        src_rows = await sources_repo.list_sources(pipeline_id)
        dest_rows = await destinations.list_destinations(pipeline_id)

        # 1. Pipeline-level active inventory (not excluded)
        inv_res = await execute(
            """
            SELECT COUNT(DISTINCT r.id)
            FROM tiktok_reels r
            JOIN tiktok_sources s ON s.id = r.source_id
            WHERE s.pipeline_id = :pid AND r.status != 'excluded'
            """,
            {"pid": pipeline_id},
        )
        active_inventory = inv_res.rows[0][0] if inv_res.rows else 0

        # 2. Pipeline-level excluded count
        excl_res = await execute(
            """
            SELECT COUNT(DISTINCT r.id)
            FROM tiktok_reels r
            JOIN tiktok_sources s ON s.id = r.source_id
            WHERE s.pipeline_id = :pid AND r.status = 'excluded'
            """,
            {"pid": pipeline_id},
        )
        excluded_count = excl_res.rows[0][0] if excl_res.rows else 0

        # 3. Pipeline-level published video count (distinct videos successfully published with valid YouTube video ID)
        pub_video_res = await execute(
            """
            SELECT COUNT(DISTINCT r.id)
            FROM tiktok_reels r
            JOIN tiktok_sources s ON s.id = r.source_id
            WHERE s.pipeline_id = :pid
              AND (
                (r.status = 'published' AND r.youtube_video_id IS NOT NULL AND length(trim(r.youtube_video_id)) > 0)
                OR EXISTS (
                  SELECT 1 FROM tiktok_publications pub
                  WHERE pub.reel_db_id = r.id
                    AND pub.status = 'published'
                    AND pub.youtube_video_id IS NOT NULL
                    AND length(trim(pub.youtube_video_id)) > 0
                )
              )
            """,
            {"pid": pipeline_id},
        )
        published_video_count = pub_video_res.rows[0][0] if pub_video_res.rows else 0

        # 4. Pipeline-level unpublished active video count
        unpublished_count = max(0, active_inventory - published_video_count)

        # 5. Pipeline-level queue jobs breakdown:
        # - queued: waiting or scheduled to run
        # - processing: currently running
        # - failed: failed publishing jobs
        q_breakdown_res = await execute(
            """
            SELECT
                SUM(CASE WHEN status IN ('queued', 'scheduled') THEN 1 ELSE 0 END) AS queued_cnt,
                SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) AS proc_cnt,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS fail_cnt
            FROM tiktok_publish_queue
            WHERE pipeline_id = :pid
            """,
            {"pid": pipeline_id},
        )
        q_row = q_breakdown_res.rows[0] if q_breakdown_res.rows else (0, 0, 0)
        queued_jobs = (q_row[0] or 0)
        processing_jobs = (q_row[1] or 0)
        failed_jobs = (q_row[2] or 0)
        # Total waiting or active queue jobs (excludes failed, cancelled, done)
        active_queued_count = queued_jobs + processing_jobs

        sources_data = []
        for src in src_rows:
            total = await reels_repo.count_reels(src["id"])
            unpublished = await reels_repo.count_unpublished(src["id"])
            published = await reels_repo.count_published(src["id"])
            excluded = await reels_repo.count_excluded(src["id"])

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
                "active_reels": max(0, total - excluded),
                "excluded_reels": excluded,
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
            source_detail = f"{len(src_rows)} nguồn · {active_inventory} video trong kho"

        # Step 2: Inventory status
        if active_inventory == 0:
            inventory_status = "idle"
            inventory_detail = "Chưa có video trong kho"
        elif unpublished_count > 0:
            inventory_status = "ready"
            inventory_detail = f"{unpublished_count} video chưa đăng"
        else:
            inventory_status = "done"
            inventory_detail = f"{published_video_count} video đã đăng"

        # Step 3: AI Metadata status
        if ai_prepared_count > 0:
            ai_status = "ready"
            ai_detail = f"{ai_prepared_count} video đã có AI metadata"
        elif unpublished_count > 0:
            ai_status = "ready"
            ai_detail = f"{unpublished_count} video sẵn sàng tạo SEO"
        else:
            ai_status = "idle"
            ai_detail = "Đang chờ video mới"

        # Check background worker health
        import time
        from datetime import datetime
        now_ts = time.time()
        sched_state = await system_state.get_json("worker:scheduler", {})
        pub_state = await system_state.get_json("worker:publisher", {})

        sched_online = False
        if sched_state and sched_state.get("last_heartbeat"):
            try:
                hb = datetime.fromisoformat(sched_state["last_heartbeat"].replace("Z", "+00:00"))
                if abs(now_ts - hb.timestamp()) < 120:
                    sched_online = True
            except Exception:
                pass

        pub_online = False
        if pub_state and pub_state.get("last_heartbeat"):
            try:
                hb = datetime.fromisoformat(pub_state["last_heartbeat"].replace("Z", "+00:00"))
                if abs(now_ts - hb.timestamp()) < 120:
                    pub_online = True
            except Exception:
                pass

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
        elif not sched_online:
            scheduler_status = "offline"
            scheduler_detail = "Scheduler worker offline"
        elif scheduled_count > 0:
            scheduler_status = "ready"
            scheduler_detail = f"Auto ON · {scheduled_count} video đã lên lịch"
        else:
            scheduler_status = "ready"
            scheduler_detail = "Auto ON · Sẵn sàng lên lịch"

        # Step 5: Publisher status
        if processing_jobs > 0:
            publisher_status = "running"
            publisher_detail = f"Đang đăng {processing_jobs} video lên YouTube..."
        elif not pub_online:
            publisher_status = "offline"
            publisher_detail = "Publisher worker offline"
        elif active_queued_count > 0:
            publisher_status = "waiting"
            publisher_detail = f"{active_queued_count} video trong hàng đợi"
        elif published_video_count > 0:
            publisher_status = "done"
            publisher_detail = f"{published_video_count} video đã đăng"
        elif failed_jobs > 0:
            publisher_status = "idle"
            publisher_detail = f"Publisher idle · {failed_jobs} job thất bại"
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
        if unpublished_count > 0 and (ai_status == "ready" or scheduler_status == "ready"):
            active_edges.append("inventory->ai_metadata")
        if sched_enabled and (active_queued_count > 0 or scheduled_count > 0):
            active_edges.append("ai_metadata->scheduler")
        if active_queued_count > 0:
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
            # Standard metric fields expected by DTO & PipelineCard
            "inventory": active_inventory,
            "published": published_video_count,
            "queued": active_queued_count,
            "failed": failed_jobs,
            "processing": processing_jobs,
            "sources_count": len(src_rows),
            "destinations_count": len(dest_rows),
            # Legacy alias fields for backwards compatibility
            "inventory_count": active_inventory,
            "published_count": published_video_count,
            "queued_count": active_queued_count,
            "failed_count": failed_jobs,
            "processing_count": processing_jobs,
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
                "inventory": active_inventory,
                "published": published_video_count,
                "queued": active_queued_count,
                "failed": failed_jobs,
                "processing": processing_jobs,
                "total_reels": active_inventory + excluded_count,
                "unpublished": unpublished_count,
                "excluded_count": excluded_count,
                "queue_count": active_queued_count,
                "processing_count": processing_jobs,
                "failed_count": failed_jobs,
                "scheduled_count": scheduled_count,
                "ai_prepared_count": ai_prepared_count,
            },
        }

    return await get_cached(f"pipeline:{pipeline_id}:flow", _load)


@router.get("/invalidate/{pipeline_id}", dependencies=[Depends(require_admin)])
async def invalidate_cache(pipeline_id: str):
    from ..services.dashboard_cache import invalidate_pipeline
    invalidate_pipeline(pipeline_id)
    return {"status": "cache invalidated", "pipeline_id": pipeline_id}
