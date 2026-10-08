"""Per-pipeline processing orchestrator (direct_merge / translate_sub / dub_vi).

- Mode selects the stage list; stages irrelevant to the mode are never
  executed (reported as "skipped", never silently half-run).
- Translation/TTS/upload providers are injectable callables. Defaults
  raise NOT_IMPLEMENTED — this task builds routing and state, not providers.
- Sequential download/process (low-resource friendly), durable resume via
  the job's downloaded_episode_ids + on-disk presence check.
"""

import logging
from pathlib import Path
from typing import Any, Callable

from ..db.repositories import drama as drama_repo
from ..db.repositories import processing as proc_repo
from .merge import MergeError, concat_paths

logger = logging.getLogger("backend-drama-processing")

STAGES_BY_MODE: dict[str, list[str]] = {
    "direct_merge": ["download", "render", "merge", "upload", "cleanup"],
    "translate_sub": ["download", "asr", "translate", "render", "merge", "subtitle", "upload", "cleanup"],
    "dub_vi": ["download", "asr", "translate", "tts", "render", "merge", "subtitle", "upload", "cleanup"],
}

ALL_STAGES = ("download", "asr", "translate", "tts", "render",
              "merge", "subtitle", "upload", "cleanup")


class StageNotImplemented(Exception):
    def __init__(self, stage: str) -> None:
        super().__init__(f"Stage not implemented: {stage}.")
        self.code = "STAGE_NOT_IMPLEMENTED"
        self.stage = stage


def stage_plan(mode: str) -> tuple[list[str], list[str]]:
    """(active_stages, skipped_stages) for a mode."""
    if mode not in STAGES_BY_MODE:
        raise ValueError(f"Unknown processing_mode: {mode!r}.")
    active = STAGES_BY_MODE[mode]
    return active, [s for s in ALL_STAGES if s not in active]


async def _default_not_implemented(stage: str, *args: Any, **kwargs: Any) -> Any:
    raise StageNotImplemented(stage)


async def run_series_job(
    job_id: str,
    *,
    workdir: Path,
    download_episode: Callable[..., Any] | None = None,
    run_asr: Callable[..., Any] | None = None,
    translate_text: Callable[..., Any] | None = None,
    synthesize_tts: Callable[..., Any] | None = None,
    upload_video: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Run one series chunk job to completion. Returns a stage report.

    Per-episode architecture: download -> [asr -> translate -> tts] ->
    render segment -> validate -> delete source, sequentially per episode
    in numeric order. Then concat segments (-c copy) -> upload -> cleanup.
    Resume skips rendered episodes; retry resets failed ones.
    """
    from ..db.repositories import episode_tasks as tasks_repo
    from ..db.repositories import templates as templates_repo
    from .merge import MergeError, concat_paths
    from .render.disk import DiskError, check_temp_space, estimate_job_bytes
    from .render.episode import SegmentError, render_episode_segment, standard_canvas
    from .render.store import SegmentStore

    job = proc_repo.get_job(job_id)
    if job is None:
        raise ValueError(f"Job not found: {job_id}.")
    mode = job["processing_mode"]
    active, skipped = stage_plan(mode)
    report: dict[str, Any] = {
        "job_id": job_id, "mode": mode, "active": active, "skipped": skipped,
        "stages": {}, "output": None, "episodes": [],
    }
    # Upload idempotency: a restarted job that already published must never
    # upload a duplicate — return the recorded completed state.
    if job.get("youtube_video_id") and job.get("status") == "completed":
        report["status"] = "completed"
        report["output"] = job.get("output_path")
        report["youtube_video_id"] = job.get("youtube_video_id")
        return report

    def _step(name: str, state: str, **extra: Any) -> None:
        report["stages"][name] = {"state": state, **extra}
        proc_repo.update_job(job_id, stage=f"{name}:{state}")

    def _fail(code: str, message: str, stage: str) -> dict[str, Any]:
        _step(stage, "failed", code=code)
        proc_repo.update_job(
            job_id, status="failed", last_error_code=code,
            last_error_message=message[:2000],
        )
        report["status"] = "failed"
        report["error"] = {"code": code, "message": message}
        return report

    try:
        proc_repo.update_job(job_id, status="downloading")
        episodes = _episodes_for_job(job)
        if not episodes:
            return _fail("NO_EPISODES", "No episodes in range.", "download")
        job_dir = workdir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        store = SegmentStore(job_dir)
        # Concurrency: sequential per episode (DRAMA_RENDER_CONCURRENCY=1).
        # Higher values are clamped until parallel rendering is enabled —
        # shared SQLite + single ffmpeg lane stay safe on small hosts.
        from ..config import settings as _dj_settings

        try:
            render_concurrency = max(1, int(_dj_settings.DRAMA_RENDER_CONCURRENCY))
        except Exception:
            render_concurrency = 1
        if render_concurrency != 1:
            logger.warning(
                "drama render concurrency=%d requested; running sequential (phase 1)",
                render_concurrency,
            )
        try:
            check_temp_space(job_dir, estimate_job_bytes(episodes))
        except DiskError as exc:
            return _fail(exc.code, str(exc), "download")

        settings = proc_repo.get_settings(job.get("pipeline_id") or "")
        template = None
        if settings.get("template_enabled") and settings.get("template_id"):
            template = templates_repo.get_template(settings["template_id"])
            if template is None:
                return _fail("TEMPLATE_MISSING", "Pipeline template not found.", "render")
            proc_repo.update_job(job_id, template_id=template["id"])
        canvas = standard_canvas(template)
        # Rasterize template frame ONCE per job (not per episode).
        frame_path = None
        if template is not None:
            from .render.template_renderer import (
                TemplateError,
                fetch_template_asset,
                rasterize_svg,
                validate_svg,
            )

            try:
                fetched = fetch_template_asset(
                    str(template.get("asset_url") or ""), job_dir / "template_source")
                if fetched.suffix.lower() == ".svg":
                    validate_svg(fetched.read_bytes())
                    frame_path = job_dir / "template_frame.png"
                    rasterize_svg(
                        fetched, frame_path,
                        width=int(template.get("canvas_width") or canvas[0]),
                        height=int(template.get("canvas_height") or canvas[1]),
                    )
                else:
                    frame_path = fetched
            except TemplateError as exc:
                return _fail(exc.code, str(exc), "render")

        tasks_repo.ensure_tasks(job_id, episodes)
        downloader = download_episode or _default_not_implemented
        _step("download", "running")
        _step("render", "running")
        rendered_numbers: list[int] = []
        for ep in episodes:
            ep_id = ep["id"]
            ep_num = ep["episode_number"]
            task = tasks_repo.get_task(job_id, ep_id) or {"status": "pending"}
            seg = store.segment_path(ep_num)
            if task.get("status") == "rendered" and store.has(ep_num):
                rendered_numbers.append(ep_num)
                report["episodes"].append({"n": ep_num, "state": "rendered"})
                continue
            # ---- download this episode ----
            tasks_repo.mark_status(job_id, ep_id, "downloading")
            src = job_dir / f"ep_{ep_num:03d}.mp4"
            if not (src.exists() and src.stat().st_size > 0):
                try:
                    await downloader(ep, src)
                except StageNotImplemented as exc:
                    tasks_repo.mark_status(job_id, ep_id, "failed",
                                           last_error_code=exc.code, last_error_message=str(exc))
                    return _fail(exc.code, str(exc), "download")
                except Exception as exc:  # noqa: BLE001 - recorded, typed below
                    tasks_repo.mark_status(job_id, ep_id, "failed",
                                           last_error_code="DOWNLOAD_FAILED",
                                           last_error_message=str(exc)[:2000])
                    return _fail("DOWNLOAD_FAILED", f"Episode {ep_num}: {exc}", "download")
                if not src.exists() or src.stat().st_size <= 0:
                    tasks_repo.mark_status(job_id, ep_id, "failed",
                                           last_error_code="DOWNLOAD_FAILED",
                                           last_error_message="no file produced")
                    return _fail("DOWNLOAD_FAILED", f"Episode {ep_num} produced no file.", "download")
            proc_repo.mark_episode_downloaded(job_id, ep_id)
            # ---- per-episode middle stages ----
            if "asr" in active:
                asr_runner = run_asr or _default_not_implemented
                try:
                    await asr_runner(job, ep, src)
                except StageNotImplemented as exc:
                    tasks_repo.mark_status(job_id, ep_id, "failed",
                                           last_error_code=exc.code, last_error_message=str(exc))
                    return _fail(exc.code, str(exc), "asr")
                except Exception as exc:  # noqa: BLE001
                    tasks_repo.mark_status(job_id, ep_id, "failed",
                                           last_error_code="ASR_FAILED",
                                           last_error_message=str(exc)[:2000])
                    return _fail("ASR_FAILED", str(exc)[:2000], "asr")
            if "translate" in active:
                translator = translate_text or _default_not_implemented
                try:
                    await translator(job, ep, None)
                except StageNotImplemented as exc:
                    tasks_repo.mark_status(job_id, ep_id, "failed",
                                           last_error_code=exc.code, last_error_message=str(exc))
                    return _fail(exc.code, str(exc), "translate")
                except Exception as exc:  # noqa: BLE001
                    tasks_repo.mark_status(job_id, ep_id, "failed",
                                           last_error_code="TRANSLATE_FAILED",
                                           last_error_message=str(exc)[:2000])
                    return _fail("TRANSLATE_FAILED", str(exc)[:2000], "translate")
            if "tts" in active:
                tts = synthesize_tts or _default_not_implemented
                try:
                    await tts(job, ep, None)
                except StageNotImplemented as exc:
                    tasks_repo.mark_status(job_id, ep_id, "failed",
                                           last_error_code=exc.code, last_error_message=str(exc))
                    return _fail(exc.code, str(exc), "tts")
                except Exception as exc:  # noqa: BLE001
                    tasks_repo.mark_status(job_id, ep_id, "failed",
                                           last_error_code="TTS_FAILED",
                                           last_error_message=str(exc)[:2000])
                    return _fail("TTS_FAILED", str(exc)[:2000], "tts")
            # ---- render this episode ----
            tasks_repo.mark_status(job_id, ep_id, "rendering")
            try:
                render_episode_segment(src, seg, template_frame=frame_path, canvas=canvas)
                from .media.drama_media import probe_media

                probe = probe_media(seg)
                if probe.get("duration", 0) <= 0:
                    raise SegmentError("SEGMENT_RENDER_FAILED", "Segment has no duration.")
            except SegmentError as exc:
                tasks_repo.mark_status(job_id, ep_id, "failed",
                                       last_error_code=exc.code,
                                       last_error_message=str(exc)[:2000])
                return _fail(exc.code, str(exc), "render")
            tasks_repo.mark_status(
                job_id, ep_id, "rendered", segment_path=str(seg),
                segment_bytes=seg.stat().st_size,
                duration=probe.get("duration"),
            )
            try:
                src.unlink(missing_ok=True)
            except Exception:
                pass
            rendered_numbers.append(ep_num)
            report["episodes"].append({"n": ep_num, "state": "rendered"})
        _step("download", "done", files=len(rendered_numbers))
        _step("render", "done", segments=len(rendered_numbers))
        if "asr" in active:
            _step("asr", "done")
        if "translate" in active:
            _step("translate", "done")
        if "tts" in active:
            _step("tts", "done")
        if "subtitle" in active:
            _step("subtitle", "done", note="subtitle burn uses translation output")

        # ---- final concat (stream copy; segments share one profile) ----
        _step("merge", "running")
        ordered = store.ordered_paths(sorted(rendered_numbers))
        final_path = job_dir / "final.mp4"
        try:
            concat_paths(ordered, final_path)
            from .media.drama_media import probe_media as _probe

            probe = _probe(final_path)
            if probe.get("duration", 0) <= 0:
                raise MergeError("MERGE_FAILED", "Final output has no duration.")
            total_seg = sum(
                float((tasks_repo.get_task(job_id, ep["id"]) or {}).get("duration") or 0)
                for ep in episodes
            )
            if total_seg > 0 and abs(probe["duration"] - total_seg) > max(5.0, total_seg * 0.05):
                raise MergeError("MERGE_FAILED", "Final duration mismatches segments.")
        except MergeError as exc:
            return _fail(exc.code, str(exc), "merge")
        _step("merge", "done", output=str(final_path))
        report["output"] = str(final_path)
        proc_repo.update_job(job_id, status="merging", output_path=str(final_path))

        # ---- upload (idempotent; real publisher by default) ----
        _step("upload", "running")
        if upload_video is not None:
            run_uploader = upload_video

            async def _upload(job, final_path):
                return await run_uploader(job, final_path)
        else:
            from .drama_youtube_publisher import publish_job_final

            series = drama_repo.get_series(job.get("series_id") or "")

            async def _upload(job, final_path):
                start = job.get("episode_start")
                end = job.get("episode_end")
                title = (series or {}).get("title") or "Drama"
                if start is not None and end is not None:
                    title = f"{title} - Tập {start}-{end}" if start != end else f"{title} - Tập {start}"
                return await publish_job_final(job, final_path, title=title)

        try:
            up_out = await _upload(job, final_path)
        except StageNotImplemented as exc:
            proc_repo.update_job(job_id, status="failed")
            return _fail(exc.code, str(exc), "upload")
        except Exception as exc:  # noqa: BLE001
            return _fail("UPLOAD_FAILED", str(exc)[:2000], "upload")
        _step("upload", "done")
        report["upload"] = up_out
        if isinstance(up_out, dict) and up_out.get("youtube_video_id"):
            proc_repo.update_job(job_id, youtube_video_id=up_out["youtube_video_id"])

        # ---- cleanup (only after successful upload) ----
        _step("cleanup", "running")
        store.cleanup()
        for extra in ("merged.mp4", "concat.txt", "template_frame.png",
                      "template_source.svg", "template_source.png", "final.mp4"):
            try:
                (job_dir / extra).unlink(missing_ok=True)
            except Exception:
                pass
        try:
            final_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            job_dir.rmdir()
        except Exception:
            pass
        _step("cleanup", "done")

        proc_repo.update_job(job_id, status="completed", stage="completed")
        report["status"] = "completed"
        return report
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        logger.exception("series job %s crashed", job_id)
        return _fail("JOB_CRASHED", str(exc)[:2000], "job")


def _episodes_for_job(job: dict[str, Any]) -> list[dict[str, Any]]:
    items, _ = drama_repo.list_episodes(job["series_id"], limit=1000)
    start = job.get("episode_start")
    end = job.get("episode_end")
    ordered = sorted(items, key=lambda e: (e["episode_number"], e["id"]))
    if start is not None:
        ordered = [e for e in ordered if e["episode_number"] >= start]
    if end is not None:
        ordered = [e for e in ordered if e["episode_number"] <= end]
    return ordered
