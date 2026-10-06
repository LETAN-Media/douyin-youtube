"""Upstream vendor health (failover pool state). No secrets exposed."""

from fastapi import APIRouter, Depends

from ..auth import require_admin
from ..services.providers import pool as pool_mod

router = APIRouter(prefix="/api/drama", tags=["drama-providers"])


@router.get("/providers/health")
async def providers_health(_: None = Depends(require_admin)) -> dict:
    """Per-upstream status snapshot: {name: {status, host, last_http}}."""
    return {"upstreams": pool_mod.pool_health()}
