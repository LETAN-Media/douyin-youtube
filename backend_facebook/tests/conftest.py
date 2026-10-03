import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("ADMIN_TOKEN", "test_admin_token")
os.environ.setdefault("TURSO_DATABASE_URL", "file:/tmp/backend_facebook_test.db")
os.environ.setdefault("TURSO_AUTH_TOKEN", "test_token")
