"""Audio job processor: resolve -> download -> audio -> SRT -> render -> AI -> upload.

One job at a time per worker. Checkpoints in Turso (stage/progress), temp
files under workdir/job_id, cleanup after success (or TTL on failure).
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("backend-audio.processor")


def _step(job_id: str, stage: str, state: str, progress: int,
          detail: str | None = None) -> None:
    from app.db.repositories import jobs as jobs_repo

    jobs_repo.update_job(job_id, stage=f"{stage}:{state}",
                         progress_percent=progress)
    jobs_repo.add_event(job_id, stage, state, detail)


def _handle_failed_inventory(inventory_id: str, code: str) -> None:
    from app.db.client import get_client
    from app.db.repositories import sources as src_repo

    client = get_client()
    row = client.execute(
        "SELECT COUNT(*) AS n FROM audio_processing_jobs WHERE inventory_id = ? "
        "AND status = 'failed'", (inventory_id,)).fetchone()
    try:
        failed_count = int(row["n"]) if row and row.get("n") is not None else 0
    except (ValueError, TypeError):
        failed_count = 0

    permanent_codes = {
        "NO_SOURCE", "INVALID_SOURCE", "NOT_FOUND", "CORRUPTED",
        "UNSUPPORTED", "UNSUPPORTED_MEDIA", "PRIVATE_VIDEO", "DOWNLOAD_REJECTED"
    }
    if code in permanent_codes or failed_count >= 2:
        src_repo.set_inventory_status(inventory_id, "failed")
        logger.warning("inventory %s marked failed (code=%s, failed_jobs=%d)",
                       inventory_id, code, failed_count)
    else:
        src_repo.set_inventory_status(inventory_id, "available")
        logger.info("inventory %s recovered to available (code=%s, failed_jobs=%d)",
                    inventory_id, code, failed_count)


def _fail(job_id: str, code: str, message: str, stage: str,
          inventory_id: str | None = None) -> dict[str, Any]:
    from app.db.repositories import jobs as jobs_repo

    jobs_repo.update_job(job_id, status="failed", stage=f"{stage}:failed",
                         last_error_code=code,
                         last_error_message=message[:2000])
    jobs_repo.add_event(job_id, stage, "failed", f"{code}: {message[:500]}")

    if not inventory_id:
        j = jobs_repo.get_job(job_id)
        if j:
            inventory_id = j.get("inventory_id")
    if inventory_id:
        _handle_failed_inventory(inventory_id, code)

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
    from app.services import loop_renderer

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
        info = await asyncio.to_thread(audio_extractor.probe_media, source_mp4)
        audio_path = job_dir / "audio.m4a"
        proc_settings = _processing_settings(pipeline_id)
        normalize_audio = bool(proc_settings.get("normalize_audio", False))
        await asyncio.to_thread(audio_extractor.extract_audio, source_mp4, audio_path, normalize=normalize_audio, threads=threads)
        probe_res = await asyncio.to_thread(audio_extractor.probe_media, audio_path)
        duration = probe_res["duration"]
    except audio_extractor.AudioError as exc:
        return _fail(job_id, exc.code, str(exc), "extracting_audio")
    # Source MP4 is no longer needed (audio.m4a feeds render) — free disk.
    try:
        source_mp4.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("job %s: could not delete source.mp4: %s", job_id, exc)

    # ---- background & template selection ----
    bg_asset = audio_repo.pick_background_asset(pipeline_id)
    if bg_asset is None:
        return _fail(job_id, "NO_BACKGROUND",
                     "Pipeline media library has no enabled background or template.",
                     "rendering")
    jobs_repo.update_job(job_id, background_asset_id=bg_asset["id"])

    # Logo selection (if enabled)
    logo_local: Path | None = None
    logos = [a for a in audio_repo.list_assets(pipeline_id, "logo")
             if a.get("enabled")]
    logo_asset = logos[0] if logos else None
    if logo_asset:
        jobs_repo.update_job(job_id, logo_asset_id=logo_asset["id"])

    # Template periodic overlay check (only if explicitly enabled AND distinct from background)
    periodic_overlay_asset = None
    if proc_settings.get("template_enabled"):
        manual_tid = proc_settings.get("template_asset_id")
        picked_overlay = None
        if manual_tid:
            for asset in audio_repo.list_assets(pipeline_id, "template"):
                if asset["id"] == manual_tid and asset.get("enabled"):
                    picked_overlay = asset
                    break
        if picked_overlay is None:
            picked_overlay = audio_repo.pick_random_template(
                pipeline_id, avoid_asset_id=bg_asset["id"] if bg_asset else None)
        if picked_overlay and bg_asset and picked_overlay["id"] == bg_asset["id"]:
            logger.info("job %s: template asset %s matches background asset, skipping overlay",
                        job_id, picked_overlay["id"])
            picked_overlay = None
        periodic_overlay_asset = picked_overlay

    # ---- rendering / fast mux ----
    _step(job_id, "rendering", "running", 60)
    final_mp4 = job_dir / "rendered.mp4"

    if periodic_overlay_asset is None:
        # Standard Fast Mux flow: template normalized & cached once on R2, then stream copy
        from app.services import template_cache

        norm_template_path = job_dir / "normalized_template.mp4"
        try:
            norm_template_path, cache_status, norm_elapsed = await asyncio.to_thread(
                template_cache.get_or_create_optimized_template,
                pipeline_id=pipeline_id,
                bg_asset=bg_asset,
                dest_path=norm_template_path,
                orientation=proc_settings.get("orientation", "landscape"),
                logo_asset=logo_asset,
                logo_position=proc_settings.get("logo_position", "top-right"),
                threads=threads,
                temp_dir=job_dir,
            )
            jobs_repo.add_event(job_id, "template_cache", cache_status,
                                f"{cache_status} in {norm_elapsed:.2f}s")
        except template_cache.TemplateCacheError as exc:
            return _fail(job_id, exc.code, str(exc), "rendering")

        try:
            t_mux0 = time.perf_counter()
            await asyncio.to_thread(
                loop_renderer.fast_mux_loop_video,
                normalized_video=norm_template_path,
                audio=audio_path,
                output=final_mp4,
                duration=duration,
            )
            mux_elapsed = time.perf_counter() - t_mux0
            jobs_repo.add_event(job_id, "rendering", "fast_mux",
                                f"elapsed={mux_elapsed:.2f}s")
        except loop_renderer.RenderError as exc:
            return _fail(job_id, exc.code, str(exc), "rendering")
    else:
        # Fallback to standard render if periodic overlay is explicitly active
        bg_suffix = Path(bg_asset.get("file_name") or bg_asset.get("object_key") or "bg.mp4").suffix or ".mp4"
        bg_local = job_dir / f"background{bg_suffix}"
        try:
            r2_storage.download_file(bg_asset["object_key"], bg_local)
        except r2_storage.R2Error as exc:
            err_code = "BACKGROUND_R2_OBJECT_MISSING" if ("DOWNLOAD_FAILED" in exc.code or "NOT_FOUND" in exc.code or "404" in str(exc)) else exc.code
            return _fail(job_id, err_code, str(exc), "rendering")

        tmpl_local = None
        tmpl_len = None
        t_suffix = Path(periodic_overlay_asset.get("file_name") or periodic_overlay_asset.get("object_key") or "tmpl.mp4").suffix or ".mp4"
        tmpl_local = job_dir / f"template{t_suffix}"
        try:
            r2_storage.download_file(periodic_overlay_asset["object_key"], tmpl_local)
            tmpl_len = audio_extractor.probe_video(tmpl_local)["duration"]
            jobs_repo.update_job(job_id, template_asset_id=periodic_overlay_asset["id"])
        except Exception:
            tmpl_local = None
            tmpl_len = None

        if logo_asset:
            try:
                logo_local = job_dir / "logo.png"
                r2_storage.download_file(logo_asset["object_key"], logo_local)
            except Exception:
                logo_local = None

        try:
            await asyncio.to_thread(
                loop_renderer.build_loop_video,
                background=bg_local, audio=audio_path, output=final_mp4,
                duration=duration, logo=logo_local,
                logo_position=proc_settings.get("logo_position", "top-right"),
                orientation=proc_settings.get("orientation", "landscape"),
                threads=threads,
                template=tmpl_local,
                template_interval_s=float(proc_settings.get("template_interval_s") or 600),
                template_duration_s=tmpl_len,
            )
        except loop_renderer.RenderError as exc:
            return _fail(job_id, exc.code, str(exc), "rendering")

    # Verify final MP4 integrity
    try:
        final_probe = await asyncio.to_thread(audio_extractor.probe_video, final_mp4)
        if final_probe.get("duration", 0) <= 0:
            return _fail(job_id, "RENDER_INVALID", "Final MP4 duration is invalid.", "rendering")
    except Exception as exc:
        return _fail(job_id, "RENDER_INVALID", f"Final MP4 verification failed: {exc}", "rendering")

    # ---- AI metadata ----
    ai_cfg = audio_repo.get_ai_settings(pipeline_id)
    title, description, hashtags = resolve_initial_metadata(job, resolved,
                                                            inventory)
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
    try:
        from app.services import youtube_publisher as publisher

        pub = await publisher.publish_final(
            job=job, video_path=final_mp4, title=title,
            description=description, hashtags=hashtags,
            srt_path=None,
            captions_required=False)
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
    # Completion is persisted BEFORE cleanup: progress never decreases again.
    jobs_repo.update_job(job_id, status="completed", stage="completed:done",
                         progress_percent=100,
                         youtube_url=pub.get("youtube_url"),
                         last_error_code=None,
                         last_error_message=None)
    jobs_repo.add_event(job_id, "completed", "done",
                        pub.get("youtube_url"))

    # ---- cleanup (best-effort; never touches R2 library or stored SRT) ----
    try:
        for p in job_dir.glob("*"):
            if p.is_file():
                try:
                    p.unlink(missing_ok=True)
                except Exception as exc:
                    logger.warning("cleanup %s: %s", p.name, type(exc).__name__)
        chunks = job_dir / "chunks"
        if chunks.exists():
            shutil.rmtree(chunks, ignore_errors=True)
        try:
            job_dir.rmdir()
        except OSError:
            pass
    except Exception as exc:
        logger.warning("job %s cleanup warning: %s", job_id, exc)
    jobs_repo.add_event(job_id, "cleanup", "done")
    return {"job_id": job_id, "status": "completed",
            "youtube_video_id": pub["youtube_video_id"],
            "youtube_url": pub.get("youtube_url"),
            "captions": pub.get("captions"),
            "disclosure": pub.get("disclosure")}


async def _generate_srt(job_id: str, pipeline_id: str, audio_path: Path,
                        duration: float, job_dir: Path) -> Path:
    """Legacy stub: Subtitles have been removed from audio pipeline."""
    merged = job_dir / "subs.srt"
    merged.write_text("", encoding="utf-8")
    return merged


def resolve_initial_metadata(job: dict[str, Any], resolved: dict[str, Any],
                             inventory: dict[str, Any] | None
                             ) -> tuple[str, str, list[str]]:
    """Safe title/description/hashtags precedence (never crashes on types).

    1. Manual values stored on the job (manual route sets ai_* + status manual).
    2. Resolver title.
    3. Inventory caption.
    4. Default "Audio".
    Manual description/hashtags are preserved when AI is disabled.
    """
    def _clean_title(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        text = value.strip()
        return text[:100].rstrip() if text else None

    manual_title = _clean_title((job or {}).get("ai_title"))
    if manual_title:
        description = (job.get("ai_description") or "")
        if not isinstance(description, str):
            description = ""
        try:
            tags = json.loads(job.get("ai_hashtags_json") or "[]")
        except Exception:
            tags = []
        if not isinstance(tags, list):
            tags = []
        return manual_title, description.strip()[:5000], [str(t) for t in tags]

    title = _clean_title(resolved.get("title"))
    if title:
        return title, "", []
    title = _clean_title((inventory or {}).get("caption"))
    if title:
        return title, "", []
    return "Audio", "", []


def _processing_settings(pipeline_id: str) -> dict[str, Any]:
    from app.db.client import get_client
    from app.db.repositories import audio as audio_repo

    row = get_client().execute(
        "SELECT * FROM audio_processing_settings WHERE pipeline_id = ?",
        (pipeline_id,)).fetchone()
    if row is None:
        bg_src = audio_repo.get_background_source(pipeline_id)
        return {"subtitle_mode": "none", "srt_auto_generate": False,
                "srt_required": False, "srt_object_key": None,
                "logo_position": "top-right",
                "orientation": "landscape", "template_enabled": False,
                "template_asset_id": None, "template_interval_s": 600,
                "background_source": bg_src, "normalize_audio": False}
    d = dict(row)
    if "background_source" not in d or not d["background_source"]:
        d["background_source"] = audio_repo.get_background_source(pipeline_id)
    # Subtitles are disabled across all audio pipelines
    d["subtitle_mode"] = "none"
    d["srt_auto_generate"] = False
    d["srt_required"] = False
    d["srt_object_key"] = None
    return d


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
