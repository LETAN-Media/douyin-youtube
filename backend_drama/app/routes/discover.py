"""Live Drama discovery route (upstream live feeds & search)."""

from fastapi import APIRouter, Depends, Query

from ..auth import require_admin
from ..services.discovery import discover_movies

router = APIRouter(prefix="/api/drama", tags=["drama-discover"])


@router.get("/discover")
async def discover_drama_series(
    provider: str = Query(default="all"),
    query: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=100),
    _: None = Depends(require_admin),
) -> dict:
    """Fetch live series metadata from upstream providers directly.

    Results are ephemeral (cached in memory) and not saved to local DB.
    """
    return await discover_movies(
        provider=provider,
        query=query,
        limit=limit,
    )
