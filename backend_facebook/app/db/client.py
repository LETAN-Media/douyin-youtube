import logging
from typing import Any

from libsql_client import Client, create_client

from ..config import settings

logger = logging.getLogger("backend-facebook.db")

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        if not settings.TURSO_DATABASE_URL:
            raise RuntimeError("TURSO_DATABASE_URL is not configured")
        _client = create_client(
            settings.TURSO_DATABASE_URL,
            auth_token=settings.TURSO_AUTH_TOKEN,
        )
    return _client


async def execute(sql: str, params: dict[str, Any] | None = None) -> Any:
    client = get_client()
    return await client.execute(sql, params)


async def migrate() -> None:
    client = get_client()
    await client.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
        """
    )
    rows = await client.execute("SELECT version FROM schema_migrations ORDER BY id")
    applied = {row[0] for row in rows.rows}
    statements = _load_schema()
    version = "20241003_01"
    if version not in applied:
        for sql_stmt in statements:
            if sql_stmt.strip():
                await client.execute(sql_stmt)
        await client.execute(
            "INSERT INTO schema_migrations (version) VALUES (:version)",
            {"version": version},
        )


def _load_schema() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS facebook_pipelines (
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
        CREATE TABLE IF NOT EXISTS facebook_sources (
            id TEXT PRIMARY KEY,
            pipeline_id TEXT NOT NULL,
            page_id TEXT NOT NULL,
            page_name TEXT NOT NULL,
            reels_url TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            initial_scan_completed INTEGER NOT NULL DEFAULT 0,
            crawl_complete INTEGER NOT NULL DEFAULT 0,
            discovered_total INTEGER NOT NULL DEFAULT 0,
            last_scan_at TEXT,
            last_scan_status TEXT,
            last_scan_error TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS facebook_reels (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            reel_id TEXT NOT NULL,
            reel_url TEXT,
            caption TEXT,
            thumbnail_url TEXT,
            source_published_at TEXT,
            discovered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            status TEXT NOT NULL DEFAULT 'new',
            retry_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            youtube_video_id TEXT,
            youtube_published_at TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            UNIQUE(source_id, reel_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS youtube_destinations (
            id TEXT PRIMARY KEY,
            pipeline_id TEXT NOT NULL,
            account_id TEXT,
            channel_id TEXT,
            channel_name TEXT,
            visibility TEXT NOT NULL DEFAULT 'public',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS publications (
            id TEXT PRIMARY KEY,
            reel_db_id TEXT NOT NULL,
            destination_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            youtube_video_id TEXT,
            started_at TEXT,
            published_at TEXT,
            last_error TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            UNIQUE(reel_db_id, destination_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS scan_runs (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            completed_at TEXT,
            discovered_count INTEGER NOT NULL DEFAULT 0,
            inserted_count INTEGER NOT NULL DEFAULT 0,
            existing_count INTEGER NOT NULL DEFAULT 0,
            crawl_complete INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'running',
            error TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_facebook_reels_source_id_status ON facebook_reels(source_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_facebook_reels_status_discovered_at ON facebook_reels(status, discovered_at)",
        "CREATE INDEX IF NOT EXISTS idx_facebook_sources_pipeline_id ON facebook_sources(pipeline_id)",
        "CREATE INDEX IF NOT EXISTS idx_publications_destination_id_status ON publications(destination_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_scan_runs_source_id_started_at ON scan_runs(source_id, started_at)",
    ]
