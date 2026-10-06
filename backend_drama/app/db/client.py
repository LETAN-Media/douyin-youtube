"""SQLite client with versioned, idempotent migrations.

Phase 1 runs on local SQLite (stdlib only, no driver needed). A non-file
DRAMA_TURSO_URL is reserved for shared libSQL storage in a later phase;
until then the service boots with db=not_configured for DB-backed routes
while /health stays green.
"""

import logging
import sqlite3
import threading
from pathlib import Path

from app.config import settings

logger = logging.getLogger("backend-drama-db")

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def db_configured() -> tuple[bool, str]:
    url = (settings.DRAMA_TURSO_URL or "").strip()
    if not url:
        return True, "sqlite"
    if url.startswith("file:"):
        return True, "sqlite"
    return False, "not_configured"


def _sqlite_path() -> Path:
    url = (settings.DRAMA_TURSO_URL or "").strip()
    if url.startswith("file:"):
        return Path(url[len("file:"):])
    return Path(settings.DRAMA_DB_PATH)


def get_client() -> sqlite3.Connection:
    """Process-wide SQLite connection (check_same_thread=False + lock)."""
    global _conn
    ok, _ = db_configured()
    if not ok:
        raise RuntimeError("Database is not configured (DRAMA_TURSO_URL).")
    with _lock:
        if _conn is None:
            path = _sqlite_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(str(path), check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
        return _conn


def reset_client() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
            _conn = None


MIGRATIONS: list[tuple[str, list[str]]] = [
    (
        "drama_001",
        [
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS drama_pipelines (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                auto_publish INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS drama_sources (
                id TEXT PRIMARY KEY,
                pipeline_id TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT 'rapidix',
                source_url TEXT,
                external_series_id TEXT,
                name TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_scan_at TEXT,
                scan_cursor TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS drama_series (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT 'rapidix',
                external_series_id TEXT NOT NULL,
                title TEXT,
                description TEXT,
                thumbnail_url TEXT,
                total_episodes INTEGER,
                metadata_json TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                UNIQUE(provider, external_series_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS drama_episodes (
                id TEXT PRIMARY KEY,
                series_id TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT 'rapidix',
                external_episode_id TEXT,
                episode_number INTEGER NOT NULL,
                title TEXT,
                source_url TEXT,
                thumbnail_url TEXT,
                duration REAL,
                status TEXT NOT NULL DEFAULT 'new',
                published_at TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                UNIQUE(provider, external_episode_id)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_episodes_series ON drama_episodes(series_id, episode_number)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_episodes_series_number ON drama_episodes(series_id, episode_number)",
            "CREATE INDEX IF NOT EXISTS idx_episodes_status ON drama_episodes(status)",
            "CREATE INDEX IF NOT EXISTS idx_series_source ON drama_series(source_id)",
        ],
    ),
]


def migrate() -> list[str]:
    """Apply pending migrations in order. Idempotent. Returns applied versions."""
    conn = get_client()
    applied: list[str] = []
    with _lock:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version TEXT PRIMARY KEY, "
            "applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')))"
        )
        have = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
        for version, statements in MIGRATIONS:
            if version in have:
                continue
            for sql in statements:
                conn.execute(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
            )
            conn.commit()
            applied.append(version)
    if applied:
        logger.info("drama migrations applied: %s", applied)
    return applied
