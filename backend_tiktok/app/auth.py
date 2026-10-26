import logging
import os
import secrets

logger = logging.getLogger("backend-tiktok.auth")


def is_valid_token(provided: str | None) -> bool:
    """Constant-time comparison against ADMIN_TOKEN."""
    expected = os.environ.get("ADMIN_TOKEN", "").strip()
    if not expected or not provided:
        return False
    return secrets.compare_digest(expected, provided)


def require_valid_token_or_raise(provided: str | None) -> None:
    if not is_valid_token(provided):
        raise PermissionError("Invalid admin token")
