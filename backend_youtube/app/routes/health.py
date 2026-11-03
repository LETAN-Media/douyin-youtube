from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.db.session import get_session
from app.db.repositories import pipelines as pipeline_repo

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok", "service": "backend-youtube", "version": "1.0.0"}


@router.get("/health/db")
async def health_db(session: AsyncSession = Depends(get_session)):
    from sqlalchemy import text
    try:
        await session.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"error": "DB_ERROR", "message": str(exc)})
