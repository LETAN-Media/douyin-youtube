"""Pipeline inventory: every episode across the pipeline's series.

Strict episode_number ASC ordering — the future scheduler must walk
episodes in order and never pick randomly.
"""

from fastapi import APIRouter, Depends

from ..auth import require_admin
from ..db.client import get_client
from ..db.repositories import drama as repo
from ..db.repositories.drama import _row_to_episode
from ._common import _err

router = APIRouter(prefix="/api/drama", tags=["drama-inventory"])


@router.get("/pipelines/{pipeline_id}/inventory")
async def pipeline_inventory(
    pipeline_id: str, status: str | None = None, limit: int = 500,
    offset: int = 0, _: None = Depends(require_admin),
) -> dict:
    if repo.get_pipeline(pipeline_id) is None:
        raise _err(404, "PIPELINE_NOT_FOUND", "Pipeline not found.")
    conn = get_client()
    where = "s.pipeline_id = :pid"
    params: dict = {"pid": pipeline_id}
    if status:
        where += " AND r.status = :status"
        params["status"] = status
    total = conn.execute(
        "SELECT COUNT(*) FROM drama_episodes r "
        "JOIN drama_series t ON t.id = r.series_id "
        "JOIN drama_sources s ON s.id = t.source_id "
        f"WHERE {where}",
        params,
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT r.* FROM drama_episodes r "
        "JOIN drama_series t ON t.id = r.series_id "
        "JOIN drama_sources s ON s.id = t.source_id "
        f"WHERE {where} ORDER BY r.episode_number ASC, r.id ASC "
        "LIMIT :limit OFFSET :offset",
        {**params, "limit": max(1, min(limit, 1000)), "offset": max(0, offset)},
    ).fetchall()
    return {"items": [_row_to_episode(r) for r in rows], "total": total}
