"""backend-drama: series/episode inventory service (Phase 1)."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import settings
from .db.client import db_configured, migrate
from .routes import health, inventory, pipelines, series, sources

logger = logging.getLogger("backend-drama")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    ok, state = db_configured()
    if ok:
        try:
            applied = migrate()
            if applied:
                logger.info("drama migrations applied: %s", applied)
        except Exception as exc:
            logger.exception("drama migration failed: %s", exc)
    else:
        logger.warning("database not configured (db=%s); DB routes will 500.", state)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="backend-drama", version=settings.VERSION)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        from fastapi import HTTPException as FastAPIHTTPException

        if isinstance(exc, FastAPIHTTPException):
            raise exc
        logger.exception("unhandled error: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "INTERNAL_ERROR", "message": "Internal error."},
        )

    app.include_router(health.router)
    app.include_router(pipelines.router)
    app.include_router(sources.router)
    app.include_router(series.router)
    app.include_router(inventory.router)
    return app


app = create_app()
