import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db.client import migrate
from .routes import health


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.SERVICE_NAME,
        version=settings.VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()] or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)

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

