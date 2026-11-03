import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("ADMIN_TOKEN", "test_admin_token")
import tempfile as _tempfile

_TMP_DB_DIR = _tempfile.mkdtemp(prefix="backend_youtube_test_")
_TEST_DB_PATH = f"sqlite+aiosqlite:///{_TMP_DB_DIR}/test.db"
os.environ.setdefault("DATABASE_URL", _TEST_DB_PATH)
os.environ.setdefault("YOUTUBE_DATA_API_KEY", "test_yt_key")
os.environ.setdefault("FACEBOOK_APP_ID", "test_app_id")
os.environ.setdefault("FACEBOOK_APP_SECRET", "test_app_secret")
os.environ.setdefault("FACEBOOK_PAGE_ACCESS_TOKEN", "test_page_token")
os.environ.setdefault("FACEBOOK_GRAPH_API_VERSION", "v19.0")
os.environ.setdefault("TOOLNET_AI_ENABLED", "true")
os.environ.setdefault("TOOLNET_BASE_URL", "http://toolnet-test")
os.environ.setdefault("TOOLNET_API_KEY", "test_toolnet_key")
os.environ.setdefault("TOOLNET_MODEL", "gpt-4o-mini")
os.environ.setdefault("FASTSAVER_API_KEY", "test_fastsaver_key")
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "ZmDfcTF7_60GrrY167zsiPd67pEvs0aGOv2oasOM1Pg=")


@pytest.fixture
def db_url():
    return os.environ["DATABASE_URL"]


@pytest.fixture
async def db_engine():
    """Function-scoped engine bound to the current test's event loop."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool
    from app.db.base import Base
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from app.db import session as session_mod
    session_mod.force_engine_rebuild()
    asf = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with asf() as session:
        yield session
        await session.rollback()
