"""Admin auth. Mirrors backend_facebook semantics: X-Admin-Token header."""

from fastapi import Header, HTTPException

from app.config import settings


def _err(status_code: int, error: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": error, "message": message})


async def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    expected = (settings.DRAMA_ADMIN_TOKEN or "").strip()
    if not expected:
        raise _err(500, "ADMIN_NOT_CONFIGURED", "DRAMA_ADMIN_TOKEN is not configured.")
    if (x_admin_token or "") != expected:
        raise _err(401, "UNAUTHORIZED", "Invalid admin token.")
