"""backend-audio: Facebook audio -> loop video -> YouTube."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.db.client import db_configured
from app.db.migrations import migrate
from app.routes import (ai_metadata, health, inventory, jobs, media, pipelines,
                        scheduler, sources, youtube)

logger = logging.getLogger("backend-audio")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    app.state.db_ready = False
    try:
        applied = migrate()
        if applied:
            logger.info("audio migrations applied: %s", applied)
    except Exception as exc:
        # Fail fast: a worker must never run without a migrated database.
        logger.exception("audio migration failed; worker will NOT start: %s", exc)
        yield
        return
    app.state.db_ready = True
    try:
        from app.services.scanner import recover_interrupted_scans

        recover_interrupted_scans()
    except Exception as exc:
        logger.warning("scan recovery failed: %s", exc)
    try:
        from app.workers.audio_worker import start

        start()
    except Exception as exc:
        logger.warning("worker failed to start: %s", exc)
    yield
    try:
        from app.workers.audio_worker import stop

        await stop()
    except Exception:
        pass


def create_app() -> FastAPI:
    app = FastAPI(title="backend-audio", version=settings.VERSION,
                  lifespan=lifespan)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        from fastapi import HTTPException as FastAPIHTTPException

        if isinstance(exc, FastAPIHTTPException):
            raise exc
        logger.exception("unhandled error: %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500,
                            content={"error": "INTERNAL_ERROR",
                                     "message": "Internal error."})

    app.include_router(health.router)
    app.include_router(pipelines.router)
    app.include_router(sources.router)
    app.include_router(inventory.router)
    app.include_router(media.router)
    app.include_router(youtube.router)
    app.include_router(scheduler.router)
    app.include_router(ai_metadata.router)
    app.include_router(jobs.router)
    return app


app = create_app()
