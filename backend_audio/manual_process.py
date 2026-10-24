#!/usr/bin/env python3
"""Manually process Facebook video with custom template."""
import asyncio
import logging
import os
import uuid
from pathlib import Path

os.environ["PHIMTAT_MAX_BYTES"] = str(2 * 1024 * 1024 * 1024)

from app.db.client import get_client
from app.config import settings
from app.services.r2_storage import upload_file

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("manual")

async def main():
    client = get_client()
    
    # Cấu hình
    fb_url = "https://www.facebook.com/share/v/1Dgs81uA9v/?mibextid=wwXIfr"
    pipeline_id = "apl_fb648f456bc0"
    template_local = "/root/douyin-youtube/backend_audio/assets/template/copy_D4113EBE-74D2-4E43-9ECE-002F6DD3CF97.MOV"
    
    # Upload template
    logger.info("Uploading custom template...")
    template_key = f"audio/pipelines/{pipeline_id}/templates/custom_{uuid.uuid4().hex[:8]}.MOV"
    upload_file(template_local, template_key)
    logger.info("Template uploaded: %s", template_key)
    
    # Tạo media asset record
    template_id = f"amedia_{uuid.uuid4().hex[:12]}"
    client.execute("""
        INSERT INTO audio_media_assets 
        (id, pipeline_id, kind, object_key, file_name, mime, width, height, duration_seconds, bytes, enabled)
        VALUES (?, ?, 'template', ?, 'custom_template.MOV', 'video/quicktime', 1080, 1920, 10, 2000000, 1)
    """, (template_id, pipeline_id, template_key))
    logger.info("Media asset created: %s", template_id)
    
    # Tạo job
    jid = f"ajob_{uuid.uuid4().hex[:12]}"
    logger.info("Creating job %s", jid)
    client.execute("""
        INSERT INTO audio_processing_jobs 
        (id, pipeline_id, mode, manual_url, background_asset_id, status, stage)
        VALUES (?, ?, 'manual', ?, ?, 'queued', 'pending')
    """, (jid, pipeline_id, fb_url, template_id))
    
    print("\n" + "="*60)
    print(f"✅ Job created: {jid}")
    print(f"📺 Facebook URL: {fb_url}")
    print(f"🎨 Template: {template_key}")
    print(f"🔄 Pipeline: Audio Truyện ({pipeline_id})")
    print("="*60)
    print("\nWorker đang xử lý job. Để xem tiến trình:")
    print(f"  watch -n 2 'curl -s http://localhost:8080/api/audio/jobs/{jid} -H \"X-Admin-Token: Tan@230997\"'")
    print("\nHoặc kiểm tra trong database:")
    print(f"  SELECT status, stage, progress_percent, last_error_message FROM audio_processing_jobs WHERE id = '{jid}'")
    print("="*60 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
