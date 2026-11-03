from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from ..config import settings


def _build_ssl_args() -> dict | None:
    url = (settings.DATABASE_URL or "").strip()
    if not url or url.startswith("sqlite"):
        return None
    return {"sslmode": settings.DB_SSL_MODE}


def _database_url() -> str:
    url = settings.require_database_url()
    if url.startswith("sqlite:"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    if url.startswith("postgresql+asyncpg://"):
        return url
    if "://" not in url:
        return "postgresql+asyncpg://" + url
    return url


def _is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite+aiosqlite://")


def _is_postgres_url(url: str) -> bool:
    return url.startswith("postgresql+asyncpg://")


_engine: "object | None" = None
_async_session_factory: "async_sessionmaker[AsyncSession] | None" = None


def get_engine():
    global _engine
    if _engine is not None:
        return _engine
    url = _database_url()
    ssl_args = _build_ssl_args()
    if _is_sqlite_url(url):
        connect_args: dict = {"check_same_thread": False}
        poolclass = NullPool
        engine = create_async_engine(
            url,
            echo=settings.DB_ECHO,
            pool_pre_ping=True,
            poolclass=poolclass,
            connect_args=connect_args,
            future=True,
        )
    else:
        connect_args = ssl_args or {}
        engine = create_async_engine(
            url,
            echo=settings.DB_ECHO,
            pool_pre_ping=True,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_recycle=1800,
            connect_args=connect_args,
            future=True,
        )

        @event.listens_for(engine.sync_engine, "connect")
        def _set_timeouts(dbapi_conn, connection_record):
            try:
                dbapi_conn.execute("SET statement_timeout = 60000")
                dbapi_conn.execute("SET lock_timeout = 30000")
            except Exception:
                pass

    _engine = engine
    return _engine


def get_session_factory() -> "async_sessionmaker[AsyncSession]":
    global _async_session_factory
    if _async_session_factory is not None:
        return _async_session_factory
    engine = get_engine()
    _async_session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    return _async_session_factory


def async_session_factory() -> "async_sessionmaker[AsyncSession]":
    return get_session_factory()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


def is_sqlite() -> bool:
    return _is_sqlite_url(_database_url())


def is_postgres() -> bool:
    return _is_postgres_url(_database_url())


async def close_engine() -> None:
    global _engine, _async_session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _async_session_factory = None


def force_engine_rebuild() -> None:
    global _engine, _async_session_factory
    if _engine is not None:
        _engine = None
    _async_session_factory = None


async def init_db() -> None:
    from .base import Base
    engine = get_engine()
    if is_sqlite():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    else:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))


def get_db_url() -> str:
    return _database_url()
