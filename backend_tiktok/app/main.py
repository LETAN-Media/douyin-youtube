"""TikTok → YouTube background ingestion service.

FastAPI application with lifespan-managed background workers:
  - TikTok Scheduler (initial scan + auto replenishment)
  - Global Publisher (FIFO → YouTube upload)
  - AI Metadata Worker (ToolNet enrichment)
  - YouTube Reconciler (scheduled-publish completion)

All workers depend on provider adapters via ABCs / factory, never on
concrete provider classes.
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db.client import close_client, migrate
from .services.youtube_schedule_reconciler import reconciler_loop
from .services.tiktok_ai_worker import ai_worker_loop
from .services.tiktok_global_publisher import publisher_loop
from .services.tiktok_scheduler import scheduler_loop

logger = logging.getLogger("backend-tiktok")


def _setup_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


_setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s v%s", settings.service_name, settings.version)
    await migrate()

    stop_event: asyncio.Event = asyncio.Event()
    tasks: list[asyncio.Task] = []

    if settings.tiktok_scheduler_enabled:
        tasks.append(asyncio.create_task(scheduler_loop(stop_event)))
    if settings.tiktok_reconcile_enabled:
        tasks.append(asyncio.create_task(reconciler_loop(stop_event)))
    if settings.toolnet_ai_enabled:
        tasks.append(asyncio.create_task(ai_worker_loop(stop_event)))
    if getattr(settings, "tiktok_publisher_enabled", False):
        tasks.append(asyncio.create_task(publisher_loop(stop_event)))

    for t in tasks:
        t.add_done_callback(lambda f: logger.warning("worker exited: %s", f.exception()) if f.exception() else None)

    yield

    logger.info("Shutting down %s workers", settings.service_name)
    stop_event.set()
    for t in tasks:
        try:
            await asyncio.wait_for(t, timeout=10)
        except asyncio.TimeoutError:
            t.cancel()
            logger.warning("worker did not stop in time, cancelled")
    await close_client()
    logger.info("%s stopped", settings.service_name)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.service_name,
        version=settings.version,
        lifespan=lifespan,
    )
    origins = [o.strip() for o in settings.cors_origins.split(",")]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from .routes import (
        ai_metadata,
        flow,
        health,
        inventory,
        manual,
        pipelines,
        publish,
        scan,
        schedule,
        sources,
        youtube,
    )

    app.include_router(health.router)
    app.include_router(pipelines.router)
    app.include_router(sources.router)
    app.include_router(inventory.router)
    app.include_router(scan.router)
    app.include_router(schedule.router)
    app.include_router(publish.router)
    app.include_router(flow.router)
    app.include_router(youtube.router)
    app.include_router(ai_metadata.router)
    app.include_router(manual.router)

    return app


app = create_app()
