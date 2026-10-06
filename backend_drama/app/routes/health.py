"""Health probes. /ready never calls the provider (no billable traffic)."""

from fastapi import APIRouter

from ..config import settings
from ..db.client import db_configured

router = APIRouter(tags=["drama-health"])


@router.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "backend-drama"}


@router.get("/ready")
async def ready() -> dict:
    db_ok, db_state = db_configured()
    rapidix = (
        "configured"
        if settings.rapidix_configured()
        else "missing"
    )
    ok = db_ok
    return {"ok": ok, "service": "backend-drama", "db": db_state, "rapidix": rapidix}
