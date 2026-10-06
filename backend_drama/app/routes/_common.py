"""Shared route helpers."""

from fastapi import HTTPException


def _err(status_code: int, error: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": error, "message": message})
