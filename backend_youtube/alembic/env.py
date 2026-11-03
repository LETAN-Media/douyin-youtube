"""Alembic migration environment.

Supports PostgreSQL (production, Neon) and SQLite (tests/dev).
Reads DATABASE_URL from application settings.
"""
import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402

config_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
if os.path.exists(config_file):
    fileConfig(config_file)


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def get_url() -> str:
    url = (settings.DATABASE_URL or "").strip()
    if not url:
        url = "sqlite+aiosqlite:///./alembic_test.db"
    elif url.startswith("sqlite:") and not url.startswith("sqlite+aiosqlite://"):
        url = "sqlite+aiosqlite://" + url[len("sqlite://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


def run_migrations_offline() -> None:
    migrate_url = get_url()
    context.configure(
        url=migrate_url,
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_as_batch=_is_sqlite(migrate_url),
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    migrate_url = get_url()
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=_is_sqlite(migrate_url),
        include_schemas=False,
    )
    with connection.begin():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(get_url(), poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
