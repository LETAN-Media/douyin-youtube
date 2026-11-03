from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.session import close_engine, init_db
from app.services.workers import WorkerManager

logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("backend-youtube")

_wm: WorkerManager | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _wm
    from app.db.session import get_engine
    engine = get_engine()
    if engine.url.query and "memory" in str(engine.url):
        pass
    try:
        await init_db()
    except Exception as exc:
        logger.warning("init_db failed (non-fatal): %s", settings.redact(str(exc)))
    if settings.PUBLISH_WORKER_ENABLED or settings.AI_WORKER_ENABLED or settings.SCHEDULER_ENABLED:
        _wm = WorkerManager()
        await _wm.start()
    yield
    if _wm is not None:
        await _wm.aclose()
    await close_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="YouTube → Facebook Publisher Backend",
        version=settings.VERSION,
        description="Backend for ingesting YouTube videos, processing AI captions, and publishing to Facebook Fanpages.",
        lifespan=lifespan,
        docs_url="/api/youtube-fb/docs",
        openapi_url="/api/youtube-fb/openapi.json",
    )
    origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
    if len(origins) == 1 and origins[0] == "*":
        origins = ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )
    from app.routes import health, pipelines, youtube_fb
    app.include_router(health.router, prefix="/api/youtube-fb")
    app.include_router(pipelines.router, prefix="/api/youtube-fb")
    app.include_router(youtube_fb.router, prefix="/api/youtube-fb")
    return app
