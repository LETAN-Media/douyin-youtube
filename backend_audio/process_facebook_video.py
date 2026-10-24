import asyncio
import logging
import os
import uuid
from pathlib import Path

os.environ["PHIMTAT_MAX_BYTES"] = str(2 * 1024 * 1024 * 1024)

from app.db.client import get_client
from app.config import settings
from app.services.processing import run_audio_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("process_fb")

async def main():
    client = get_client()
    
    fb_url = "https://www.facebook.com/share/v/1Dgs81uA9v/?mibextid=wwXIfr"
    pipeline_id = "apl_fb648f456bc0"
    template_path = "/root/douyin-youtube/backend_audio/assets/template/copy_D4113EBE-74D2-4E43-9ECE-002F6DD3CF97.MOV"
    
    logger.info("Checking template in database...")
    existing = client.execute("SELECT id FROM audio_media WHERE object_key LIKE '%template%' ORDER BY created_at DESC LIMIT 1").fetchone()
    
    if existing:
        template_id = existing['id']
        logger.info("Using existing template: %s", template_id)
    else:
        logger.info("Uploading template to R2...")
        from app.services.r2_storage import upload_file
        template_key = f"templates/{uuid.uuid4().hex[:12]}_template.mov"
        upload_file(template_path, template_key)
        logger.info("Template uploaded to R2: %s", template_key)
        
        media_row = client.execute(
            "INSERT INTO audio_media (id, object_key, media_type, duration_s, width, height) VALUES (?, ?, 'video', 10, 1080, 1920) RETURNING *",
            (f"amedia_{uuid.uuid4().hex[:12]}", template_key)
        ).fetchone()
        template_id = media_row['id']
    
    jid = "ajob_" + uuid.uuid4().hex[:12]
    
    logger.info("Creating job %s for URL: %s with template %s", jid, fb_url, template_id)
    client.execute("""
        INSERT INTO audio_processing_jobs (id, pipeline_id, mode, manual_url, background_asset_id, status, stage, lease_owner)
        VALUES (?, ?, 'manual', ?, ?, 'running', 'claimed', 'local-worker')
    """, (jid, pipeline_id, fb_url, template_id))
    
    workdir = Path(settings.AUDIO_WORKDIR or "/tmp/audio_work")
    workdir.mkdir(parents=True, exist_ok=True)
    
    logger.info("Processing job %s...", jid)
    try:
        result = await run_audio_job(jid, workdir=workdir)
        logger.info("SUCCESS! Job %s completed", jid)
        
        row = client.execute("SELECT * FROM audio_processing_jobs WHERE id = ?", (jid,)).fetchone()
        if row:
            print("\n" + "="*50)
            print("JOB COMPLETED SUCCESSFULLY")
            print("="*50)
            print(f"Job ID: {row.get('id')}")
            print(f"Status: {row.get('status')}")
            print(f"Title: {row.get('ai_title')}")
            print(f"YouTube Video ID: {row.get('youtube_video_id')}")
            print(f"YouTube URL: {row.get('youtube_url')}")
            print("="*50 + "\n")
    except Exception as e:
        logger.exception("FAILED job %s: %s", jid, e)

if __name__ == "__main__":
    asyncio.run(main())
