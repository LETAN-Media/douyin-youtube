import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("ADMIN_TOKEN", "test_admin_token")
os.environ.setdefault("TURSO_DATABASE_URL", "file:/tmp/tiktok_test.db")
os.environ.setdefault("TURSO_TOKEN", "test_token")

TEST_DB_PATH = Path("/tmp/tiktok_test.db")
TEST_DB_URL = f"file:{TEST_DB_PATH}"


def setup_env() -> None:
    os.environ.setdefault("ADMIN_TOKEN", "test_admin_token")
    os.environ.setdefault("TURSO_DATABASE_URL", TEST_DB_URL)
    os.environ.setdefault("TURSO_TOKEN", "test_token")


def teardown() -> None:
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
