import asyncio
import logging
import os
from pathlib import Path
import uuid

# Override size cap to 2GB before importing settings
os.environ["PHIMTAT_MAX_BYTES"] = str(2 * 1024 * 1024 * 1024)

from app.db.client import get_client
from app.config import settings
from app.services.processing import run_audio_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("run_job")

async def main():
    client = get_client()
    url = "/root/FDown.vn_Tai_video_Facebook_MP3_77fe.mp4.mp3"
    pipeline_id = "apl_fb648f456bc0"
    template_id = "amedia_1c5f0d3899ba"
    jid = "ajob_" + uuid.uuid4().hex[:12]
    
    logger.info("Enqueuing and claiming job %s for url: %s with template %s", jid, url, template_id)
    client.execute("""
        INSERT INTO audio_processing_jobs (id, pipeline_id, mode, manual_url, background_asset_id, status, stage, lease_owner)
        VALUES (?, ?, 'manual', ?, ?, 'running', 'claimed', 'local-worker')
    """, (jid, pipeline_id, url, template_id))
    
    workdir = Path(settings.AUDIO_WORKDIR or "/tmp/audio_work")
    workdir.mkdir(parents=True, exist_ok=True)
    
    logger.info("Starting run_audio_job(%s)...", jid)
    try:
        result = await run_audio_job(jid, workdir=workdir)
        logger.info("SUCCESS! Job %s completed with result: %s", jid, result)
        
        # Query final job details
        row = client.execute("SELECT * FROM audio_processing_jobs WHERE id = ?", (jid,)).fetchone()
        if row:
            print("=========================================")
            print("JOB RESULT:")
            print(f"ID: {row.get('id')}")
            print(f"Status: {row.get('status')}")
            print(f"Title: {row.get('ai_title')}")
            print(f"YouTube Video ID: {row.get('youtube_video_id')}")
            print(f"YouTube URL: {row.get('youtube_url')}")
            print("=========================================")
    except Exception as e:
        logger.exception("FAILED %s: %s", jid, e)

if __name__ == "__main__":
    asyncio.run(main())
