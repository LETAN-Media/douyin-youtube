from fastapi import APIRouter
from pydantic import BaseModel

from ..config import settings


class HealthResponse(BaseModel):
    ok: bool
    service: str
    version: str


router = APIRouter()


@router.get("/health", response_model=HealthResponse, include_in_schema=False)
async def health() -> HealthResponse:
    return HealthResponse(ok=True, service="backend-facebook", version="1.0.0")


def _redact(message: str) -> str:
    redacted = message or ""
    for secret in (
        settings.ADMIN_TOKEN,
        settings.TURSO_AUTH_TOKEN,
        settings.RAPIDAPI_KEY,
        settings.RAPIDAPI_KEY_FALLBACK,
    ):
        if secret and len(secret) > 4:
            redacted = redacted.replace(secret, "***")
            # also mask bearer-style tail fragments
            if len(secret) > 12:
                redacted = redacted.replace(secret[-12:], "***")
    return redacted[:500]


@router.get("/ready", include_in_schema=False)
async def ready() -> dict:
    """Liveness + Turso reachability (no secrets in output)."""
    info: dict = {"ok": True, "service": "backend-facebook", "db": "unknown"}
    if not settings.TURSO_DATABASE_URL:
        return {**info, "ok": False, "db": "error", "detail": "TURSO_DATABASE_URL missing"}
    try:
        from ..db.client import get_client

        client = get_client()
        rows = await client.execute("SELECT COUNT(*) FROM schema_migrations")
        count = rows.rows[0][0] if rows.rows else 0
        return {**info, "db": "ok", "migrations": count}
    except Exception as exc:
        return {
            **info,
            "ok": False,
            "db": "error",
            "detail": _redact(f"{type(exc).__name__}: {exc}"),
        }

