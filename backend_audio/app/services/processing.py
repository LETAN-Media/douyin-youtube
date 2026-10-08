"""Audio job processor: resolve -> download -> audio -> SRT -> render -> AI -> upload.

One job at a time per worker. Checkpoints in Turso (stage/progress), temp
files under workdir/job_id, cleanup after success (or TTL on failure).
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger("backend-audio.processor")


def _step(job_id: str, stage: str, state: str, progress: int,
          detail: str | None = None) -> None:
    from app.db.repositories import jobs as jobs_repo

    jobs_repo.update_job(job_id, stage=f"{stage}:{state}",
                         progress_percent=progress)
    jobs_repo.add_event(job_id, stage, state, detail)


def _fail(job_id: str, code: str, message: str, stage: str) -> dict[str, Any]:
    from app.db.repositories import jobs as jobs_repo

    jobs_repo.update_job(job_id, status="failed", stage=f"{stage}:failed",
                         last_error_code=code,
                         last_error_message=message[:2000])
    jobs_repo.add_event(job_id, stage, "failed", f"{code}: {message[:500]}")
    return {"job_id": job_id, "status": "failed",
            "error": {"code": code, "message": message}}


async def run_audio_job(job_id: str, *, workdir: Path,
                        timeout_s: int = 7200) -> dict[str, Any]:
    from app.config import settings
    from app.db.repositories import jobs as jobs_repo
    from app.db.repositories import sources as src_repo

    job = jobs_repo.get_job(job_id)
    if job is None:
        raise ValueError(f"Job not found: {job_id}.")
    if job.get("youtube_video_id") and job.get("status") == "completed":
        return {"job_id": job_id, "status": "completed",
                "youtube_video_id": job["youtube_video_id"], "already": True}

    pipeline_id = job["pipeline_id"]
    job_dir = workdir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    source_url = None
    inventory = None
    if job.get("inventory_id"):
        from app.db.client import get_client

        inventory = get_client().execute(
            "SELECT * FROM audio_inventory WHERE id = ?",
            (job["inventory_id"],)).fetchone()
        if inventory:
            inventory = dict(inventory)
            source_url = inventory.get("canonical_url")
            src_repo.set_inventory_status(inventory["id"], "processing")
    if not source_url:
        source_url = job.get("manual_url")
    if not source_url:
        return _fail(job_id, "NO_SOURCE", "Job has no source URL.", "resolving")

    try:
        return await asyncio.wait_for(
            _run_stages(job, job_dir, source_url, inventory), timeout=timeout_s)
    except asyncio.TimeoutError:
        return _fail(job_id, "JOB_TIMEOUT", "Job exceeded timeout.", "running")


async def _run_stages(job: dict, job_dir: Path, source_url: str,
                      inventory: dict | None) -> dict[str, Any]:
    from app.config import settings
    from app.db.repositories import jobs as jobs_repo
    from app.db.repositories import audio as audio_repo
    from app.db.repositories import sources as src_repo
    from app.services import audio_extractor, r2_storage, snapvideo
    from app.services import loop_renderer, subtitle_service

    job_id, pipeline_id = job["id"], job["pipeline_id"]
    threads = int(settings.AUDIO_FFMPEG_THREADS or 2)

    # ---- resolving ----
    _step(job_id, "resolving", "running", 5)
    try:
        resolved = await snapvideo.resolve_media_url(source_url)
        media_url = resolved["media_url"]
    except snapvideo.SnapVideoError as exc:
        return _fail(job_id, exc.code, str(exc), "resolving")
    jobs_repo.add_event(job_id, "resolving", "done", media_url[:120])

    # ---- downloading ----
    _step(job_id, "downloading", "running", 12)
    source_mp4 = job_dir / "source.mp4"
    try:
        await snapvideo.stream_download(media_url, source_mp4)
    except snapvideo.SnapVideoError as exc:
        return _fail(job_id, exc.code, str(exc), "downloading")

    # ---- extracting audio ----
    _step(job_id, "extracting_audio", "running", 25)
    try:
        info = audio_extractor.probe_media(source_mp4)
        audio_path = job_dir / "audio.m4a"
        audio_extractor.extract_audio(source_mp4, audio_path, threads=threads)
        duration = audio_extractor.probe_media(audio_path)["duration"]
    except audio_extractor.AudioError as exc:
        return _fail(job_id, exc.code, str(exc), "extracting_audio")

    # ---- background selection ----
    bg_asset = audio_repo.pick_random_background(pipeline_id)
    bg_local = job_dir / "background.mp4"
    if bg_asset is None:
        return _fail(job_id, "NO_BACKGROUND",
                     "Pipeline media library has no enabled background.",
                     "rendering")
    try:
        r2_storage.download_file(bg_asset["object_key"], bg_local)
    except r2_storage.R2Error as exc:
        return _fail(job_id, exc.code, str(exc), "rendering")
    jobs_repo.update_job(job_id, background_asset_id=bg_asset["id"])

    # ---- subtitles ----
    proc_settings = _processing_settings(pipeline_id)
    subtitle_mode = proc_settings.get("subtitle_mode", "youtube_captions")
    srt_local: Path | None = None
    if subtitle_mode in ("youtube_captions", "hardsub"):
        if proc_settings.get("srt_object_key"):
            _step(job_id, "subtitles", "running", 35)
            try:
                srt_local = job_dir / "subs.srt"
                r2_storage.download_file(proc_settings["srt_object_key"], srt_local)
                jobs_repo.update_job(job_id,
                                     srt_object_key=proc_settings["srt_object_key"])
            except r2_storage.R2Error as exc:
                return _fail(job_id, exc.code, str(exc), "subtitles")
        elif proc_settings.get("srt_auto_generate"):
            _step(job_id, "generating_srt", "running", 35)
            try:
                srt_local = await _generate_srt(job_id, pipeline_id, audio_path,
                                                duration, job_dir)
            except subtitle_service.SubtitleError as exc:
                if proc_settings.get("srt_required"):
                    return _fail(job_id, exc.code, str(exc), "generating_srt")
                jobs_repo.add_event(job_id, "generating_srt", "skipped",
                                    f"{exc.code} (optional)")

    # ---- template overlay (auto random or manual pick) ----
    template_local: Path | None = None
    template_len: float | None = None
    if proc_settings.get("template_enabled"):
        picked = None
        manual_tid = proc_settings.get("template_asset_id")
        if manual_tid:
            for asset in audio_repo.list_assets(pipeline_id, "template"):
                if asset["id"] == manual_tid and asset.get("enabled"):
                    picked = asset
                    break
        if picked is None:
            picked = audio_repo.pick_random_template(pipeline_id)
        if picked is not None:
            try:
                template_local = job_dir / "template.mp4"
                r2_storage.download_file(picked["object_key"], template_local)
                template_len = audio_extractor.probe_media(
                    template_local)["duration"]
                jobs_repo.update_job(job_id, template_asset_id=picked["id"])
                jobs_repo.add_event(job_id, "rendering", "template",
                                    f"{picked['id']} ({template_len:.1f}s)")
            except Exception as exc:
                jobs_repo.add_event(job_id, "rendering", "template_skipped",
                                    f"{type(exc).__name__} (non-blocking)")
                template_local = None

    # ---- rendering ----
    _step(job_id, "rendering", "running", 60)
    logo_local: Path | None = None
    logos = [a for a in audio_repo.list_assets(pipeline_id, "logo")
             if a.get("enabled")]
    if logos:
        try:
            logo_local = job_dir / "logo.png"
            r2_storage.download_file(logos[0]["object_key"], logo_local)
            jobs_repo.update_job(job_id, logo_asset_id=logos[0]["id"])
        except r2_storage.R2Error:
            logo_local = None
    final_mp4 = job_dir / "rendered.mp4"
    try:
        loop_renderer.build_loop_video(
            background=bg_local, audio=audio_path, output=final_mp4,
            duration=duration, logo=logo_local,
            logo_position=proc_settings.get("logo_position", "top-right"),
            orientation=proc_settings.get("orientation", "landscape"),
            threads=threads,
            template=template_local,
            template_interval_s=float(
                proc_settings.get("template_interval_s") or 600),
            template_duration_s=template_len)
    except loop_renderer.RenderError as exc:
        return _fail(job_id, exc.code, str(exc), "rendering")

    # ---- AI metadata ----
    ai_cfg = audio_repo.get_ai_settings(pipeline_id)
    title = (resolved.get("title") or inventory or {}).get("caption") or "Audio"
    if isinstance(title, dict):
        title = title.get("caption") or "Audio"
    description, hashtags = "", []
    if ai_cfg.get("enabled"):
        _step(job_id, "ai_metadata", "running", 78)
        try:
            from app.services import ai_metadata as ai_svc

            channel = _channel_name(pipeline_id)
            generated = await ai_svc.generate_metadata(
                ai_svc.AiContext(
                    genre=ai_cfg.get("genre"),
                    source_title=resolved.get("title"),
                    source_caption=(inventory or {}).get("caption") if inventory else None,
                    audio_duration_s=duration,
                    channel_name=channel,
                    custom_prompt=ai_cfg.get("system_prompt")),
                ai_cfg)
            title, description, hashtags = (generated.title, generated.description,
                                            generated.hashtags)
            jobs_repo.update_job(
                job_id, ai_title=title, ai_description=description,
                ai_hashtags_json=json.dumps(hashtags, ensure_ascii=False),
                ai_metadata_status="generated")
        except ai_svc.MetadataError as exc:
            return _fail(job_id, exc.code, str(exc), "ai_metadata")

    # ---- uploading ----
    _step(job_id, "uploading", "running", 88)
    captions_required = (subtitle_mode == "youtube_captions"
                         and proc_settings.get("srt_required", True)
                         and srt_local is not None)
    try:
        from app.services import youtube_publisher as publisher

        pub = await publisher.publish_final(
            job=job, video_path=final_mp4, title=title,
            description=description, hashtags=hashtags,
            srt_path=srt_local,
            captions_required=captions_required)
    except publisher.PublisherError as exc:
        return _fail(job_id, exc.code, str(exc), "uploading")

    # ---- record publication + inventory ----
    from app.db.client import get_client

    dest = _last_destination(pipeline_id)
    client = get_client()
    pub_id = f"apub_{job_id[:12]}"
    fb_vid = (inventory or {}).get("facebook_video_id")
    client.execute(
        "INSERT INTO audio_publications (id, pipeline_id, inventory_id, job_id, "
        "destination_id, facebook_video_id, canonical_url, youtube_video_id, "
        "youtube_url, title, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'published') "
        "ON CONFLICT(pipeline_id, destination_id, facebook_video_id) DO UPDATE SET "
        "youtube_video_id=excluded.youtube_video_id, youtube_url=excluded.youtube_url, "
        "title=excluded.title, status='published'",
        (pub_id, pipeline_id, job.get("inventory_id"), job_id,
         (dest or {}).get("id"), fb_vid, source_url, pub["youtube_video_id"],
         pub.get("youtube_url"), title))
    client.commit()
    if inventory:
        src_repo.set_inventory_status(inventory["id"], "published")
    jobs_repo.update_job(job_id, status="completed", stage="completed:done",
                         progress_percent=100,
                         youtube_url=pub.get("youtube_url"))

    # ---- cleanup ----
    _step(job_id, "cleanup", "running", 97)
    for name in ("source.mp4", "audio.m4a", "rendered.mp4", "background.mp4",
                 "logo.png", "subs.srt"):
        try:
            (job_dir / name).unlink(missing_ok=True)
        except Exception:
            pass
    chunks = job_dir / "chunks"
    if chunks.exists():
        shutil.rmtree(chunks, ignore_errors=True)
    try:
        job_dir.rmdir()
    except OSError:
        pass
    jobs_repo.add_event(job_id, "cleanup", "done")
    return {"job_id": job_id, "status": "completed",
            "youtube_video_id": pub["youtube_video_id"],
            "youtube_url": pub.get("youtube_url"),
            "captions": pub.get("captions"),
            "disclosure": pub.get("disclosure")}


async def _generate_srt(job_id: str, pipeline_id: str, audio_path: Path,
                        duration: float, job_dir: Path) -> Path:
    from app.services import r2_storage, subtitle_service

    chunks_dir = job_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    plan = subtitle_service.split_plan(duration)
    done: list[tuple[float, str]] = []
    for idx, (start, end) in enumerate(plan):
        chunk_audio = chunks_dir / f"chunk_{idx:03d}.m4a"
        subtitle_service.slice_audio_for_chunk(audio_path, start, end, chunk_audio)
        chunk_srt = chunks_dir / f"chunk_{idx:03d}.srt"
        subtitle_service.transcribe_with_bridge(chunk_audio, chunk_srt)
        done.append((start, str(chunk_srt)))
        try:
            chunk_audio.unlink(missing_ok=True)
        except Exception:
            pass
    merged = job_dir / "subs.srt"
    merged.write_text(subtitle_service.merge_chunks(done), encoding="utf-8")
    key = f"audio/pipelines/{pipeline_id}/srt/{job_id}.srt"
    r2_storage.upload_file(merged, key, content_type="application/x-subrip")
    from app.db.repositories import jobs as jobs_repo

    jobs_repo.update_job(job_id, srt_object_key=key)
    return merged


def _processing_settings(pipeline_id: str) -> dict[str, Any]:
    from app.db.client import get_client

    row = get_client().execute(
        "SELECT * FROM audio_processing_settings WHERE pipeline_id = ?",
        (pipeline_id,)).fetchone()
    if row is None:
        return {"subtitle_mode": "youtube_captions", "srt_auto_generate": True,
                "srt_required": True, "logo_position": "top-right",
                "orientation": "landscape", "template_enabled": False,
                "template_asset_id": None, "template_interval_s": 600}
    return dict(row)


def _channel_name(pipeline_id: str) -> str | None:
    from app.db.repositories import audio as audio_repo

    for dest in audio_repo.list_destinations(pipeline_id):
        if dest.get("connected"):
            return dest.get("channel_title") or dest.get("channel_id")
    return None


def _last_destination(pipeline_id: str) -> dict | None:
    from app.db.repositories import audio as audio_repo

    dests = [d for d in audio_repo.list_destinations(pipeline_id)
             if d.get("connected")]
    return dests[0] if dests else None
