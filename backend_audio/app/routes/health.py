from fastapi import APIRouter

from app.db.client import db_configured
from app.workers.audio_worker import status as worker_status

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    ok, state = db_configured()
    return {"ok": ok, "service": "backend-audio", "db": state,
            "worker": worker_status()}


@router.get("/ready")
async def ready() -> dict:
    from app.db.client import get_client

    get_client().execute("SELECT 1").fetchone()
    return {"ready": True}
