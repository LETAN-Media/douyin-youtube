import logging
from typing import Any

from libsql_client import Client, create_client

from ..config import settings

logger = logging.getLogger("backend-facebook.db")

_client: Client | None = None


def normalize_db_url(url: str) -> str:
    """Use HTTP transport for remote Turso (libsql:// needs ws, often blocked).

    Local file: URLs are untouched (tests + local dev).
    """
    if url.startswith("libsql://"):
        return "https://" + url[len("libsql://") :]
    return url


def get_client() -> Client:
    global _client
    if _client is None:
        if not settings.TURSO_DATABASE_URL:
            raise RuntimeError("TURSO_DATABASE_URL is not configured")
        _client = create_client(
            normalize_db_url(settings.TURSO_DATABASE_URL),
            auth_token=settings.TURSO_AUTH_TOKEN,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        try:
            close = getattr(_client, "close", None)
            if close is not None:
                result = close()
                if result is not None:
                    await result
        except Exception as exc:
            logger.warning("db client close skipped: %s", exc)
        finally:
            _client = None


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
    if "20241003_01" not in applied:
        for sql_stmt in _load_schema():
            if sql_stmt.strip():
                await client.execute(sql_stmt)
        await client.execute(
            "INSERT INTO schema_migrations (version) VALUES (:version)",
            {"version": "20241003_01"},
        )
    if "20241003_02" not in applied:
        for sql_stmt in _migration_02_statements(await _facebook_sources_notnull(client)):
            if sql_stmt.strip():
                await client.execute(sql_stmt)
        await client.execute(
            "INSERT INTO schema_migrations (version) VALUES (:version)",
            {"version": "20241003_02"},
        )
    if "20241003_03" not in applied:
        await client.execute("ALTER TABLE scan_runs ADD COLUMN stop_reason TEXT")
        await client.execute(
            "INSERT INTO schema_migrations (version) VALUES (:version)",
            {"version": "20241003_03"},
        )
    if "20241003_04" not in applied:
        await client.execute("ALTER TABLE scan_runs ADD COLUMN scan_mode TEXT")
        await client.execute(
            "UPDATE scan_runs SET scan_mode = 'initial' WHERE scan_mode IS NULL"
        )
        await client.execute(
            "INSERT INTO schema_migrations (version) VALUES (:version)",
            {"version": "20241003_04"},
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
            page_name TEXT,
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
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_facebook_sources_pipeline_page ON facebook_sources(pipeline_id, page_id)",
        "CREATE INDEX IF NOT EXISTS idx_publications_destination_id_status ON publications(destination_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_scan_runs_source_id_started_at ON scan_runs(source_id, started_at)",
    ]


async def _facebook_sources_notnull(client: Any) -> bool:
    """True if existing facebook_sources.page_name still has a NOT NULL constraint."""
    try:
        info = await client.execute("PRAGMA table_info(facebook_sources)")
    except Exception:
        return False
    for row in info.rows or []:
        # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
        if len(row) >= 4 and row[1] == "page_name":
            return bool(row[3])
    return False


def _migration_02_statements(page_name_notnull: bool) -> list[str]:
    statements = [
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_facebook_sources_pipeline_page "
        "ON facebook_sources(pipeline_id, page_id)",
    ]
    if page_name_notnull:
        # SQLite cannot DROP a NOT NULL constraint; rebuild the table (data-preserving).
        statements += [
            """
            CREATE TABLE IF NOT EXISTS facebook_sources_new (
                id TEXT PRIMARY KEY,
                pipeline_id TEXT NOT NULL,
                page_id TEXT NOT NULL,
                page_name TEXT,
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
            INSERT OR IGNORE INTO facebook_sources_new
                (id, pipeline_id, page_id, page_name, reels_url, enabled,
                 initial_scan_completed, crawl_complete, discovered_total,
                 last_scan_at, last_scan_status, last_scan_error, created_at, updated_at)
            SELECT id, pipeline_id, page_id, page_name, reels_url, enabled,
                 initial_scan_completed, crawl_complete, discovered_total,
                 last_scan_at, last_scan_status, last_scan_error, created_at, updated_at
            FROM facebook_sources
            """,
            "DROP TABLE facebook_sources",
            "ALTER TABLE facebook_sources_new RENAME TO facebook_sources",
            "CREATE INDEX IF NOT EXISTS idx_facebook_sources_pipeline_id ON facebook_sources(pipeline_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_facebook_sources_pipeline_page "
            "ON facebook_sources(pipeline_id, page_id)",
        ]
    return statements
