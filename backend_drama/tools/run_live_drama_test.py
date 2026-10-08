import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

# Add backend_drama to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.db.client import get_client
from app.db.repositories import drama as drama_repo
from app.db.repositories import processing as proc_repo
from app.db.repositories import youtube as yt_repo
from app.services.processing import run_series_job
from app.services.media.drama_media import probe_media
from app.services.drama_youtube_oauth import load_credentials
from googleapiclient.discovery import build

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("live-drama-test")

PIPELINE_SLUG = "test-rapidix-pipeline"


async def main():
    conn = get_client()

    # PHASE A: Audit
    logger.info("=== PHASE A: AUDIT PIPELINE ===")
    p_row = conn.execute("SELECT * FROM drama_pipelines WHERE slug = ?", (PIPELINE_SLUG,)).fetchone()
    if not p_row:
        raise RuntimeError(f"Pipeline with slug {PIPELINE_SLUG} not found")
    pipeline_id = p_row["id"] if hasattr(p_row, "keys") else p_row[0]
    pipeline_name = p_row["name"] if hasattr(p_row, "keys") else p_row[1]
    logger.info("Found pipeline: %s (id: %s)", pipeline_name, pipeline_id)

    # Series
    series_rows = conn.execute(
        "SELECT t.* FROM drama_series t JOIN drama_sources s ON s.id = t.source_id WHERE s.pipeline_id = ?",
        (pipeline_id,),
    ).fetchall()
    if not series_rows:
        raise RuntimeError(f"No series found in pipeline {pipeline_id}")
    if len(series_rows) > 1:
        raise RuntimeError(f"Multiple series found in pipeline: {len(series_rows)}. Ambiguous!")
    
    series = series_rows[0]
    series_id = series["id"] if hasattr(series, "keys") else series[0]
    series_title = series["title"] if hasattr(series, "keys") else series[4]
    logger.info("Found series: %s (id: %s)", series_title, series_id)

    # Episodes 1 & 2
    ep1_row = conn.execute("SELECT * FROM drama_episodes WHERE series_id = ? AND episode_number = 1", (series_id,)).fetchone()
    ep2_row = conn.execute("SELECT * FROM drama_episodes WHERE series_id = ? AND episode_number = 2", (series_id,)).fetchone()
    if not ep1_row or not ep2_row:
        raise RuntimeError("Episode 1 or 2 not found in database!")

    ep_cols = ["id", "series_id", "provider", "external_episode_id", "episode_number", "title", "source_url", "thumbnail_url", "duration", "status", "published_at", "created_at", "updated_at"]
    ep1 = dict(ep1_row) if hasattr(ep1_row, "keys") else dict(zip(ep_cols, list(ep1_row)))
    ep2 = dict(ep2_row) if hasattr(ep2_row, "keys") else dict(zip(ep_cols, list(ep2_row)))
    logger.info("Episode 1: id=%s title=%s url=%s", ep1["id"], ep1["title"], ep1["source_url"])
    logger.info("Episode 2: id=%s title=%s url=%s", ep2["id"], ep2["title"], ep2["source_url"])

    # Settings & Destination
    p_settings = proc_repo.get_settings(pipeline_id)
    logger.info("Pipeline settings: mode=%s, auto_publish=%s, dest_id=%s", p_settings.get("processing_mode"), p_settings.get("auto_publish"), p_settings.get("youtube_destination_id"))
    dest_id = p_settings.get("youtube_destination_id")
    if not dest_id:
        raise RuntimeError("No YouTube destination configured for pipeline")
    dest = yt_repo.get_destination(dest_id)
    if not dest or not dest.get("connected"):
        raise RuntimeError("YouTube destination not connected")
    channel_id = dest.get("channel_id")
    logger.info("YouTube destination: id=%s, channel_id=%s, channel_title=%s, dest_visibility=%s", dest["id"], channel_id, dest.get("channel_title"), dest.get("visibility"))

    # Test OAuth
    logger.info("Checking YouTube OAuth credentials...")
    creds = await load_credentials(dest_id)
    yt_service = build("youtube", "v3", credentials=creds, cache_discovery=False)
    ch_res = yt_service.channels().list(part="id,snippet", mine=True).execute()
    items = ch_res.get("items", [])
    if not items:
        raise RuntimeError("Could not retrieve channel from Google OAuth")
    logger.info("OAuth PASS: Connected to channel '%s' (ID: %s)", items[0]["snippet"]["title"], items[0]["id"])

    # PHASE B: Find or create single job
    logger.info("=== PHASE B: FIND OR CREATE JOB (EP 1-2) ===")
    existing_job_row = conn.execute(
        "SELECT id, status, youtube_video_id FROM drama_series_jobs WHERE series_id = ? AND episode_start = 1 AND episode_end = 2",
        (series_id,),
    ).fetchone()

    job_id = None
    if existing_job_row:
        existing_jid = existing_job_row[0]
        existing_status = existing_job_row[1]
        existing_yt_id = existing_job_row[2]
        logger.info("Found existing job %s (status: %s, yt_id: %s)", existing_jid, existing_status, existing_yt_id)
        if existing_status == "completed" and existing_yt_id:
            logger.info("Job already completed with video ID %s. STOP to avoid duplicate!", existing_yt_id)
            print(f"ALREADY_UPLOADED: {existing_yt_id}")
            return
        job_id = existing_jid
    else:
        new_job = proc_repo.create_job(
            pipeline_id,
            series_id,
            p_settings.get("processing_mode") or "direct_merge",
            chunk_index=0,
            episode_start=1,
            episode_end=2,
        )
        job_id = new_job["id"]
        logger.info("Created new single test job: %s", job_id)

    # PHASE C, D, E, F: Execute job
    logger.info("=== EXECUTING JOB %s WITH UNLISTED VISIBILITY OVERRIDE ===", job_id)
    workdir = Path("/tmp/drama_jobs")
    workdir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    report = await run_series_job(
        job_id,
        workdir=workdir,
        visibility_override="unlisted",
    )
    total_time = time.time() - t0
    logger.info("Job finished in %.2fs. Report: %s", total_time, json.dumps(report, indent=2))

    if report.get("status") != "completed":
        raise RuntimeError(f"Job failed: {report.get('error')}")

    yt_id = report.get("youtube_video_id") or (report.get("upload") or {}).get("youtube_video_id")
    if not yt_id:
        # Check from DB
        fresh_job = proc_repo.get_job(job_id) or {}
        yt_id = fresh_job.get("youtube_video_id")

    if not yt_id:
        raise RuntimeError("No YouTube Video ID returned!")

    logger.info("Uploaded YouTube Video ID: %s", yt_id)
    video_url = f"https://www.youtube.com/watch?v={yt_id}"
    logger.info("Video URL: %s", video_url)

    # PHASE G: Verify Video on YouTube
    logger.info("=== PHASE G: VERIFY VIDEO ON YOUTUBE ===")
    v_res = yt_service.videos().list(part="id,snippet,status", id=yt_id).execute()
    v_items = v_res.get("items", [])
    if not v_items:
        raise RuntimeError(f"Uploaded video {yt_id} not found via YouTube API!")
    
    vid = v_items[0]
    privacy = vid["status"]["privacyStatus"]
    v_title = vid["snippet"]["title"]
    v_channel = vid["snippet"]["channelId"]
    logger.info("YouTube API verification: title='%s', channel=%s, privacyStatus=%s", v_title, v_channel, privacy)
    
    if privacy != "unlisted":
        raise RuntimeError(f"CRITICAL: Video privacy is '{privacy}', expected 'unlisted'!")

    # Verify database state
    db_job = proc_repo.get_job(job_id)
    logger.info("Final DB Job status: %s, stored_yt_id: %s, stage: %s", db_job.get("status"), db_job.get("youtube_video_id"), db_job.get("stage"))

    # Verify no second job was created
    all_jobs = conn.execute(
        "SELECT id, episode_start, episode_end, status FROM drama_series_jobs WHERE series_id = ?",
        (series_id,),
    ).fetchall()

    episodes_info = report.get("episodes") or []
    ep1_info = next((e for e in episodes_info if e.get("n") == 1), {})
    ep2_info = next((e for e in episodes_info if e.get("n") == 2), {})
    out_probe = report.get("output_probe") or {}

    print("\n--- RESULTS JSON ---")
    print(json.dumps({
        "pipeline_id": pipeline_id,
        "series_id": series_id,
        "series_title": series_title,
        "ep1_id": ep1["id"],
        "ep2_id": ep2["id"],
        "ep1_duration": ep1_info.get("duration"),
        "ep1_bytes": ep1_info.get("bytes"),
        "ep1_codec": ep1_info.get("codec"),
        "ep1_resolution": ep1_info.get("resolution"),
        "ep2_duration": ep2_info.get("duration"),
        "ep2_bytes": ep2_info.get("bytes"),
        "ep2_codec": ep2_info.get("codec"),
        "ep2_resolution": ep2_info.get("resolution"),
        "total_download_bytes": (ep1_info.get("bytes") or 0) + (ep2_info.get("bytes") or 0),
        "merge_output": "final.mp4",
        "merge_duration": out_probe.get("duration"),
        "merge_bytes": report.get("output_bytes") or out_probe.get("file_bytes"),
        "merge_codec": out_probe.get("codec"),
        "merge_resolution": out_probe.get("resolution"),
        "job_id": job_id,
        "job_status": db_job.get("status"),
        "youtube_video_id": yt_id,
        "youtube_video_url": video_url,
        "video_title": v_title,
        "privacy": privacy,
        "channel_id": v_channel,
        "channel_title": items[0]["snippet"]["title"],
        "total_time_seconds": round(total_time, 2),
        "all_jobs": [dict(j) if hasattr(j, "keys") else dict(zip(["id", "episode_start", "episode_end", "status"], list(j))) for j in all_jobs],
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
    os._exit(0)
