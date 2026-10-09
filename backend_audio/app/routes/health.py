from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.db.client import db_configured
from app.workers import audio_worker

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Liveness: the process is alive. Never fails on DB state."""
    ok, state = db_configured()
    return {"ok": ok, "service": "backend-audio", "db": state,
            "worker": audio_worker.status()}


@router.get("/ready")
async def ready(request: Request):
    """Readiness: DB reachable AND all migrations applied AND worker enabled.

    Fails (503, no secrets leaked) when the database is unavailable or the
    startup migration did not complete — Northflank must not route traffic.
    """
    from app.db.client import get_client
    from app.db.migrations import MIGRATIONS

    if not getattr(request.app.state, "db_ready", False):
        return JSONResponse(status_code=503, content={
            "ready": False, "reason": "startup migration incomplete"})
    try:
        client = get_client()
        client.execute("SELECT 1").fetchone()
        have = {r["version"] for r in client.execute(
            "SELECT version FROM audio_schema_migrations").fetchall()}
        missing = [v for v, _ in MIGRATIONS if v not in have]
        if missing:
            return JSONResponse(status_code=503, content={
                "ready": False, "reason": f"missing migrations: {missing}"})
    except Exception:
        return JSONResponse(status_code=503, content={
            "ready": False, "reason": "database unreachable"})
    ws = audio_worker.status()
    if not ws.get("running"):
        return JSONResponse(status_code=503, content={
            "ready": False, "reason": "worker not running"})
    return {"ready": True}
