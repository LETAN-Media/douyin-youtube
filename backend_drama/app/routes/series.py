"""Series episode listing (episode_number ASC, never random)."""

from fastapi import APIRouter, Depends

from ..auth import require_admin
from ..db.repositories import drama as repo
from ._common import _err

router = APIRouter(prefix="/api/drama", tags=["drama-series"])


@router.get("/series")
async def list_series(
    query: str | None = None, limit: int = 50, offset: int = 0,
    _: None = Depends(require_admin)
) -> dict:
    items, total = repo.list_series(query=query, limit=limit, offset=offset)
    return {"items": items, "total": total}


@router.get("/series/{series_id}/episodes")
async def list_series_episodes(
    series_id: str, status: str | None = None, limit: int = 500,
    offset: int = 0, _: None = Depends(require_admin),
) -> dict:
    if repo.get_series(series_id) is None:
        raise _err(404, "SERIES_NOT_FOUND", "Series not found.")
    items, total = repo.list_episodes(
        series_id, status=status, limit=limit, offset=offset
    )
    return {"items": items, "total": total}
