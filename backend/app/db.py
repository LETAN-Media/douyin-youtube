import logging
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import QueuePool

from app.config import settings
from app.db_retry import is_retriable_db_error


class Base(DeclarativeBase):
    pass


_engine_kwargs: dict = {
    "connect_args": settings.sqlalchemy_connect_args,
    "pool_pre_ping": True,
    "pool_recycle": settings.db_pool_recycle_seconds,
}
# libsql/remote SQLite resolves to SingletonThreadPool, which keeps one
# connection per thread (and never closes them).  That is wrong for a remote
# HTTP-based DB: concurrency creates unbounded connections and can exhaust the
# Turso connection limit.  Use a small, bounded QueuePool instead; connections
# are still used by one thread at a time (libsql is opened with
# check_same_thread=False).
if settings.sqlalchemy_url.startswith("sqlite+libsql"):
    _engine_kwargs.update(
        poolclass=QueuePool,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_use_lifo=True,
    )

engine = create_engine(settings.sqlalchemy_url, **_engine_kwargs)


SessionLocal = sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=Session,
)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


# libsql_experimental can raise ValueError (rather than DBAPIError), so the
# SQLite dialect does not automatically recognize a dropped Hrana connection.
# Never log bound parameters: credentials and video metadata can be in them.
@event.listens_for(engine, "handle_error")
def _diagnose_database_error(context):
    if is_retriable_db_error(context.original_exception):
        context.is_disconnect = True
        statement = context.statement or "<connect/commit/rollback; no SQL statement>"
        logging.getLogger("douyin-youtube-db").warning(
            "Transient database failure operation=%s exception_type=%s; connection invalidated",
            statement, type(context.original_exception).__name__,
        )
