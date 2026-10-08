"""Segment storage abstraction (local now, R2 later).

LocalSegmentStore keeps rendered segments under the job workdir. A future
R2SegmentStore will upload-on-render and fetch-on-concat behind this same
interface — the orchestrator never touches paths directly.
"""

import shutil
from pathlib import Path


class SegmentStore:
    kind = "local"

    def __init__(self, job_dir: Path) -> None:
        self.job_dir = job_dir
        self.segments_dir = job_dir / "segments"
        self.segments_dir.mkdir(parents=True, exist_ok=True)

    def segment_path(self, episode_number: int) -> Path:
        return self.segments_dir / f"segment_{episode_number:03d}.mp4"

    def has(self, episode_number: int) -> bool:
        path = self.segment_path(episode_number)
        try:
            return path.exists() and path.stat().st_size > 0
        except Exception:
            return False

    def note_rendered(self, episode_number: int) -> Path:
        return self.segment_path(episode_number)

    def ordered_paths(self, episode_numbers: list[int]) -> list[Path]:
        return [self.segment_path(n) for n in episode_numbers]

    def drop(self, episode_number: int) -> None:
        try:
            self.segment_path(episode_number).unlink(missing_ok=True)
        except Exception:
            pass

    def cleanup(self, keep_final: Path | None = None) -> None:
        """Remove segments + manifest, optionally keeping one final file."""
        for path in sorted(self.segments_dir.glob("segment_*.mp4")):
            try:
                if keep_final is not None and path.resolve() == keep_final.resolve():
                    continue
                path.unlink(missing_ok=True)
            except Exception:
                continue
        for name in ("concat.txt",):
            try:
                (self.job_dir / name).unlink(missing_ok=True)
            except Exception:
                continue
        try:
            self.segments_dir.rmdir()
        except Exception:
            pass


# R2SegmentStore will implement the same interface:
#   put on render -> remote key; get streams back bounded for concat.
#   Tracked for later; local store is used until disk preflight fails.
