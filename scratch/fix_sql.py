import re

with open("backend_audio/app/routes/pipelines.py", "r") as f:
    content = f.read()

# Replace the whole endpoint
def replace_endpoint():
    start_str = '@router.get("/pipelines/{pipeline_id}/flow-status")'
    end_str = '        }\n    }\n'
    
    start_idx = content.find(start_str)
    if start_idx == -1: return False
    
    end_idx = content.find(end_str, start_idx)
    if end_idx == -1: return False
    
    end_idx += len(end_str)
    
    new_endpoint = """@router.get("/pipelines/{pipeline_id}/flow-status")
async def get_flow_status(pipeline_id: str, _: None = Depends(require_admin)):
    from app.db.client import get_client
    
    pipe = repo.get_pipeline(pipeline_id)
    if not pipe:
        return _err(404, "PIPELINE_NOT_FOUND", "Pipeline không tồn tại.")
        
    client = get_client()
    stats = repo.pipeline_stats(pipeline_id)
    
    import sys
    from app.workers.audio_worker import status as worker_status
    worker_alive = worker_status().get("running", False) if "app.workers.audio_worker" in sys.modules else False

    # 1. Current Job
    curr_job = None
    curr_job_row = client.execute(
        "SELECT id, status, stage, progress_percent, youtube_video_id, inventory_id, manual_url, updated_at "
        "FROM audio_processing_jobs WHERE pipeline_id = ? AND status IN ('queued', 'running') "
        "ORDER BY updated_at DESC LIMIT 1", 
        (pipeline_id,)
    ).fetchone()
    
    if curr_job_row:
        c = dict(curr_job_row)
        caption = "Unknown"
        video_id = "Unknown"
        if c.get("inventory_id"):
            inv = client.execute("SELECT facebook_video_id, caption FROM audio_inventory WHERE id = ?", (c["inventory_id"],)).fetchone()
            if inv:
                caption = inv["caption"] or "Không có caption"
                video_id = inv["facebook_video_id"]
        elif c.get("manual_url"):
            video_id = c["manual_url"]
            caption = "Manual Job"
            
        curr_job = {
            "id": c["id"],
            "stage": c["stage"],
            "status": c["status"],
            "progress_percent": c["progress_percent"] or 0,
            "video_id": video_id,
            "caption": caption[:50] + "..." if len(caption) > 50 else caption,
            "updated_at": c["updated_at"]
        }

    # 2. Steps logic
    steps = [
        {"key": "source", "label": "Nguồn Facebook", "state": "idle"},
        {"key": "queue", "label": "Hàng chờ", "state": "idle"},
        {"key": "download", "label": "Đang tải", "state": "idle"},
        {"key": "extract", "label": "Tách audio", "state": "idle"},
        {"key": "template", "label": "Chọn template", "state": "idle"},
        {"key": "render", "label": "Fast Mux / Render", "state": "idle"},
        {"key": "ai", "label": "AI Metadata", "state": "idle"},
        {"key": "upload", "label": "Upload YouTube", "state": "idle"},
        {"key": "done", "label": "Hoàn thành", "state": "idle"}
    ]
    
    if pipe.get("pipeline_type") == "manual":
        steps = [s for s in steps if s["key"] not in ("source", "queue")]
        
    if pipe.get("pipeline_type") != "manual":
        if stats.get("total_sources", 0) > 0:
            next(s for s in steps if s["key"] == "source")["state"] = "done"
        if stats.get("pending_videos", 0) > 0:
            next(s for s in steps if s["key"] == "queue")["state"] = "done"
            
    if curr_job:
        stage_str = curr_job.get("stage", "") or ""
        mapping = {
            "resolving": "download",
            "downloading": "download",
            "extracting": "extract",
            "rendering": "render",
            "ai_metadata": "ai",
            "uploading": "upload",
            "completed": "done"
        }
        
        current_step_key = None
        for k, v in mapping.items():
            if k in stage_str:
                current_step_key = v
                break
        
        if not current_step_key:
            if "queued" in stage_str or "claimed" in stage_str:
                current_step_key = "download" if pipe.get("pipeline_type") == "manual" else "queue"
            else:
                current_step_key = "download"
                
        passed = True
        for s in steps:
            if s["key"] == current_step_key:
                s["state"] = "running"
                passed = False
            elif passed:
                s["state"] = "done"
            else:
                s["state"] = "idle"
                
    # 3. Queue preview
    queue = []
    if pipe.get("pipeline_type") != "manual":
        q_rows = client.execute(
            \"\"\"SELECT i.id as inventory_id, i.facebook_video_id as video_id, i.caption, i.status, s.page_name as source_label
               FROM audio_inventory i 
               LEFT JOIN audio_sources s ON i.source_id = s.id
               WHERE i.pipeline_id = ? AND i.status IN ('available', 'reserved', 'processing')
               ORDER BY CASE i.status WHEN 'processing' THEN 1 WHEN 'reserved' THEN 2 ELSE 3 END, i.discovered_at ASC
               LIMIT 10\"\"\",
            (pipeline_id,)
        ).fetchall()
        for row in q_rows:
            r = dict(row)
            cap = r.get("caption") or ""
            queue.append({
                "inventory_id": r["inventory_id"],
                "video_id": r["video_id"],
                "caption": cap[:50] + "..." if len(cap) > 50 else cap,
                "status": r["status"],
                "source_label": r.get("source_label") or "Manual"
            })
            
    # 4. Recent failures
    f_rows = client.execute(
        \"\"\"SELECT j.id as job_id, i.facebook_video_id as video_id, j.last_error_code as error_code, j.updated_at
           FROM audio_processing_jobs j
           LEFT JOIN audio_inventory i ON j.inventory_id = i.id
           WHERE j.pipeline_id = ? AND j.status = 'failed'
           ORDER BY j.updated_at DESC LIMIT 5\"\"\",
        (pipeline_id,)
    ).fetchall()
    recent_failures = []
    for r in f_rows:
        dr = dict(r)
        vid = dr.get("video_id") or "Unknown"
        recent_failures.append({
            "job_id": dr["job_id"],
            "video_id": vid,
            "error_code": dr.get("error_code") or "UNKNOWN",
            "updated_at": dr["updated_at"]
        })

    return {
        "pipeline": pipe,
        "worker_alive": worker_alive,
        "current_job": curr_job,
        "steps": steps,
        "queue_preview": queue,
        "recent_failures": recent_failures,
        "latest_success": stats.get("last_publish"),
        "counts": {
            "available": stats.get("pending_videos", 0),
            "running": stats.get("running_jobs", 0),
            "failed": stats.get("failed_jobs", 0),
            "published": stats.get("published_videos", 0)
        }
    }
"""
    
    with open("backend_audio/app/routes/pipelines.py", "w") as f:
        f.write(content[:start_idx] + new_endpoint + content[end_idx:])
    
    return True

if replace_endpoint():
    print("Replaced endpoint.")
else:
    print("Could not find endpoint to replace.")
