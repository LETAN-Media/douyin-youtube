from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .auth import is_valid_token
from .db import client as db_client

bearer_scheme = HTTPBearer(auto_error=False)


async def get_db() -> AsyncGenerator:
    """Yield a libsql client bound to the configured Turso database."""
    client = db_client.get_client()
    yield client


def require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)] = None,
) -> None:
    """Dependency that enforces ADMIN_TOKEN via Bearer header."""
    token = credentials.credentials if credentials else None
    if not is_valid_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )
