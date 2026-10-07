"""Backward-compatible re-export. Canonical implementation lives in
app.services.render.drama_merger (per final DIRECT workflow layout)."""

from .render.drama_merger import (
    MergeError,
    compatible_for_copy,
    concat_paths,
    write_concat_manifest,
)

__all__ = ["MergeError", "compatible_for_copy", "concat_paths", "write_concat_manifest"]
