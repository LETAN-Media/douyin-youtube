import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .db.client import migrate
from .routes import ai_metadata, facebook, flow, health, inventory, publish, scan, schedule, youtube

logger = logging.getLogger("backend-facebook.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await migrate()
    except Exception as exc:
        logger.error("startup migrate FAILED: %s", exc)
    # Never leave a scan_run stuck in queued/running across restarts.
    try:
        from .db.repositories import scan_runs

        recovered = await scan_runs.fail_stale_scan_runs()
        if recovered:
            logger.warning("marked %d stale scan run(s) as failed", recovered)
    except Exception as exc:
        logger.warning("stale scan recovery skipped: %s", exc)
    scheduler_task = None
    if settings.FACEBOOK_SCHEDULER_ENABLED:
        scheduler_task = asyncio.create_task(_scheduler_loop())
        logger.info(
            "scheduler loop started (poll=%ss, batch_time=%s)",
            settings.FACEBOOK_SCHEDULER_POLL_SECONDS,
            settings.FACEBOOK_SCHEDULER_BATCH_TIME,
        )
    reconciler_task = None
    if settings.FACEBOOK_RECONCILE_ENABLED:
        reconciler_task = asyncio.create_task(_reconciler_loop())
        logger.info(
            "reconciler loop started (poll=%ss)",
            settings.FACEBOOK_RECONCILE_POLL_SECONDS,
        )
    publisher_task = None
    if settings.FACEBOOK_PUBLISH_WORKER_ENABLED:
        publisher_task = asyncio.create_task(_publisher_loop())
        logger.info(
            "global publisher started (concurrency=%d, poll=%ss)",
            settings.FACEBOOK_PUBLISH_CONCURRENCY,
            settings.FACEBOOK_PUBLISH_POLL_SECONDS,
        )
    yield
    if scheduler_task is not None:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("scheduler loop stop skipped: %s", exc)
    if reconciler_task is not None:
        reconciler_task.cancel()
        try:
            await reconciler_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("reconciler loop stop skipped: %s", exc)
    if publisher_task is not None:
        publisher_task.cancel()
        try:
            await publisher_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("publisher loop stop skipped: %s", exc)
    try:
        from .db.client import close_client

        await close_client()
    except Exception as exc:
        logger.warning("db close skipped: %s", exc)


async def _scheduler_loop() -> None:
    from .services.facebook_scheduler import run_scheduler_tick

    while True:
        try:
            await run_scheduler_tick()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("scheduler tick failed: %s", exc)
        await asyncio.sleep(max(5, settings.FACEBOOK_SCHEDULER_POLL_SECONDS))


async def _reconciler_loop() -> None:
    from .services.youtube_schedule_reconciler import reconcile_due_scheduled_publications

    while True:
        try:
            result = await reconcile_due_scheduled_publications()
            if result.get("published") or result.get("errors"):
                logger.info("reconciler result: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("reconciler tick failed: %s", exc)
        await asyncio.sleep(max(5, settings.FACEBOOK_RECONCILE_POLL_SECONDS))


async def _publisher_loop() -> None:
    from .services.facebook_global_publisher import _publisher_loop as run_publisher_loop

    await run_publisher_loop(
        concurrency=settings.FACEBOOK_PUBLISH_CONCURRENCY,
        poll_seconds=settings.FACEBOOK_PUBLISH_POLL_SECONDS,
        stale_ttl_seconds=settings.FACEBOOK_PUBLISH_STALE_TTL_SECONDS,
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.SERVICE_NAME,
        version=settings.VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            return JSONResponse(status_code=exc.status_code, content=detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": detail})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()] or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(facebook.router)
    app.include_router(flow.router)
    app.include_router(scan.router)
    app.include_router(inventory.router)
    app.include_router(youtube.router)
    app.include_router(publish.router)
    app.include_router(schedule.router)
    app.include_router(ai_metadata.router)

    return app


def _validate_required_env() -> None:
    missing = []
    if not settings.ADMIN_TOKEN or settings.ADMIN_TOKEN == "CHANGE_ME_LONG_RANDOM_TOKEN":
        missing.append("ADMIN_TOKEN")
    if not settings.TURSO_DATABASE_URL:
        missing.append("TURSO_DATABASE_URL")
    if not settings.TURSO_AUTH_TOKEN:
        missing.append("TURSO_AUTH_TOKEN")
    if missing:
        print(
            f"FATAL: missing required env vars: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _validate_required_env()
    migrate()


if __name__ == "__main__":
    main()

app = create_app()
