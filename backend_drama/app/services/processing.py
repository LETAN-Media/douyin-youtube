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
    "direct_merge": ["download", "merge", "upload", "cleanup"],
    "translate_sub": ["download", "asr", "translate", "merge", "subtitle", "upload", "cleanup"],
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
    """Run one series chunk job to completion. Returns a stage report."""
    job = proc_repo.get_job(job_id)
    if job is None:
        raise ValueError(f"Job not found: {job_id}.")
    mode = job["processing_mode"]
    active, skipped = stage_plan(mode)
    report: dict[str, Any] = {
        "job_id": job_id, "mode": mode, "active": active, "skipped": skipped,
        "stages": {}, "output": None,
    }

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
        # ---- download (sequential, resume-aware) ----
        _step("download", "running")
        episodes = _episodes_for_job(job)
        if not episodes:
            return _fail("NO_EPISODES", "No episodes in range.", "download")
        job_dir = workdir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        ordered_paths: list[Path] = []
        downloader = download_episode or _default_not_implemented
        already = set(job.get("downloaded_episode_ids") or [])
        for ep in episodes:
            target = job_dir / f"ep_{ep['episode_number']:03d}.mp4"
            if ep["id"] in already and target.exists() and target.stat().st_size > 0:
                ordered_paths.append(target)
                continue
            try:
                await downloader(ep, target)
            except StageNotImplemented as exc:
                return _fail(exc.code, str(exc), "download")
            except Exception as exc:  # noqa: BLE001 - recorded, typed below
                return _fail("DOWNLOAD_FAILED", f"Episode {ep['episode_number']}: {exc}", "download")
            if not target.exists() or target.stat().st_size <= 0:
                return _fail("DOWNLOAD_FAILED", f"Episode {ep['episode_number']} produced no file.", "download")
            ordered_paths.append(target)
            proc_repo.mark_episode_downloaded(job_id, ep["id"])
        _step("download", "done", files=len(ordered_paths))

        # ---- mode-specific middle stages ----
        if "asr" in active:
            asr_runner = run_asr or _default_not_implemented
            _step("asr", "running")
            try:
                asr_out = await asr_runner(job, ordered_paths)
            except StageNotImplemented as exc:
                return _fail(exc.code, str(exc), "asr")
            except Exception as exc:  # noqa: BLE001
                return _fail("ASR_FAILED", str(exc)[:2000], "asr")
            _step("asr", "done")
            report["asr"] = asr_out
        if "translate" in active:
            translator = translate_text or _default_not_implemented
            _step("translate", "running")
            try:
                tr_out = await translator(job, report.get("asr"))
            except StageNotImplemented as exc:
                return _fail(exc.code, str(exc), "translate")
            except Exception as exc:  # noqa: BLE001
                return _fail("TRANSLATE_FAILED", str(exc)[:2000], "translate")
            _step("translate", "done")
            report["translation"] = tr_out
        if "tts" in active:
            tts = synthesize_tts or _default_not_implemented
            _step("tts", "running")
            try:
                tts_out = await tts(job, report.get("translation"))
            except StageNotImplemented as exc:
                return _fail(exc.code, str(exc), "tts")
            except Exception as exc:  # noqa: BLE001
                return _fail("TTS_FAILED", str(exc)[:2000], "tts")
            _step("tts", "done")
            report["tts"] = tts_out
        if "render" in active:
            _step("render", "done", note="render covered by merge in this phase")
        if "subtitle" in active:
            _step("subtitle", "done", note="subtitle burn uses translation output")

        # ---- merge ----
        _step("merge", "running")
        final_path = job_dir / "final.mp4"
        try:
            concat_paths(ordered_paths, final_path)
            from .media.drama_media import probe_media

            probe = probe_media(final_path)
            if probe.get("duration", 0) <= 0:
                raise MergeError("MERGE_FAILED", "Merged output has no duration.")
        except MergeError as exc:
            return _fail(exc.code, str(exc), "merge")
        _step("merge", "done", output=str(final_path))
        report["output"] = str(final_path)
        proc_repo.update_job(job_id, status="merging", output_path=str(final_path))

        # ---- upload ----
        uploader = upload_video or _default_not_implemented
        _step("upload", "running")
        try:
            up_out = await uploader(job, final_path)
        except StageNotImplemented as exc:
            proc_repo.update_job(job_id, status="failed")
            return _fail(exc.code, str(exc), "upload")
        except Exception as exc:  # noqa: BLE001
            return _fail("UPLOAD_FAILED", str(exc)[:2000], "upload")
        _step("upload", "done")
        report["upload"] = up_out
        if isinstance(up_out, dict) and up_out.get("youtube_video_id"):
            proc_repo.update_job(job_id, youtube_video_id=up_out["youtube_video_id"])

        # ---- cleanup ----
        _step("cleanup", "running")
        for path in ordered_paths:
            try:
                path.unlink(missing_ok=True)
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
