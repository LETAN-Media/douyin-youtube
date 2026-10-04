import hmac

from fastapi import Header, HTTPException, status

from .config import settings


def require_admin(
    x_admin_token: str = Header(default="", alias="X-Admin-Token"),
) -> None:
    expected = settings.ADMIN_TOKEN or ""
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "ADMIN_TOKEN_NOT_CONFIGURED", "message": "ADMIN_TOKEN is not configured"},
        )
    if not x_admin_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "UNAUTHORIZED", "message": "Missing X-Admin-Token"},
        )
    if not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "UNAUTHORIZED", "message": "Invalid admin token"},
        )
