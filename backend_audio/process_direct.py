#!/usr/bin/env python3
"""Process job directly without worker."""
import asyncio
import logging
import os
from pathlib import Path

os.environ["PHIMTAT_ENABLED"] = "false"
os.environ["PHIMTAT_MAX_BYTES"] = str(2 * 1024 * 1024 * 1024)

from app.config import settings
from app.services.processing import run_audio_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

async def main():
    job_id = "ajob_f80b3a5d8c7b"
    workdir = Path("/tmp/audio_work")
    workdir.mkdir(parents=True, exist_ok=True)
    
    print(f"Processing job {job_id}...")
    print(f"Working directory: {workdir}")
    print(f"PHIMTAT_ENABLED: {os.environ.get('PHIMTAT_ENABLED')}")
    print("-" * 60)
    
    try:
        result = await run_audio_job(job_id, workdir=workdir)
        print("\n" + "=" * 60)
        print("✅ JOB COMPLETED SUCCESSFULLY!")
        print("=" * 60)
        print(f"Result: {result}")
        
        from app.db.client import get_client
        client = get_client()
        job = client.execute("SELECT * FROM audio_processing_jobs WHERE id = ?", (job_id,)).fetchone()
        print(f"\nJob Status: {job['status']}")
        print(f"AI Title: {job['ai_title']}")
        print(f"YouTube Video ID: {job['youtube_video_id']}")
        print(f"YouTube URL: {job['youtube_url']}")
        print("=" * 60)
    except Exception as e:
        print("\n" + "=" * 60)
        print(f"❌ JOB FAILED: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
