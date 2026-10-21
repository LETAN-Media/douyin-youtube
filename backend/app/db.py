from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import QueuePool

from app.config import settings


class Base(DeclarativeBase):
    pass


_engine_kwargs: dict = {
    "connect_args": settings.sqlalchemy_connect_args,
    "pool_pre_ping": True,
    "pool_recycle": 60,
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
        pool_size=5,
        max_overflow=5,
        pool_timeout=30,
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
