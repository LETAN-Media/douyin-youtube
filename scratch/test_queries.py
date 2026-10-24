from app.db.client import get_client
from app.db.repositories import pipelines as pipe_repo

client = get_client()
pipes = pipe_repo.list_pipelines()
for p in pipes:
    if p["name"] == "Audio Truyện":
        print(f"Found pipeline: {p['id']}")
        pid = p['id']
        break
else:
    print("Could not find Audio Truyện pipeline")
    if pipes:
        pid = pipes[0]["id"]
    else:
        pid = None

if pid:
    print("--- Stats ---")
    print(pipe_repo.pipeline_stats(pid))
    
    print("--- Queue Preview ---")
    q_rows = client.execute(
        """SELECT i.id as inventory_id, i.facebook_video_id as video_id, i.caption, i.status, s.page_name as source_label
           FROM audio_inventory i 
           LEFT JOIN audio_sources s ON i.source_id = s.id
           WHERE i.pipeline_id = ? AND i.status IN ('available', 'reserved', 'processing')
           ORDER BY CASE i.status WHEN 'processing' THEN 1 WHEN 'reserved' THEN 2 ELSE 3 END, i.discovered_at ASC
           LIMIT 5""",
        (pid,)
    ).fetchall()
    for row in q_rows:
        print(dict(row))
        
    print("--- Failures ---")
    f_rows = client.execute(
        """SELECT j.id as job_id, i.facebook_video_id as video_id, j.last_error_code as error_code, j.updated_at
           FROM audio_processing_jobs j
           LEFT JOIN audio_inventory i ON j.inventory_id = i.id
           WHERE j.pipeline_id = ? AND j.status = 'failed'
           ORDER BY j.updated_at DESC LIMIT 5""",
        (pid,)
    ).fetchall()
    for row in f_rows:
        print(dict(row))
        
