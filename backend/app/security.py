import hmac

from fastapi import Header, HTTPException, status

from app.config import settings


def require_admin(
    x_admin_token: str = Header(
        default="",
        alias="X-Admin-Token",
    ),
) -> None:
    expected = settings.admin_token

    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ADMIN_TOKEN chưa được cấu hình",
        )

    if not x_admin_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Thiếu X-Admin-Token",
        )

    if not hmac.compare_digest(
        x_admin_token,
        expected,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin token không hợp lệ",
        )
