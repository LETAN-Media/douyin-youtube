import logging
from typing import Any

from libsql_client import Client, create_client

from ..config import settings

logger = logging.getLogger("backend-tiktok.db")

_client: Client | None = None


def normalize_db_url(url: str) -> str:
    """Use HTTP transport for remote Turso (libsql:// needs ws, often blocked).

    Local file: URLs are untouched (tests + local dev).
    """
    if url.startswith("libsql://"):
        return "https://" + url[len("libsql://"):]
    return url


def get_client() -> Client:
    global _client
    if _client is None:
        if not settings.turso_database_url:
            raise RuntimeError("TURSO_DATABASE_URL is not configured")
        _client = create_client(
            normalize_db_url(settings.turso_database_url),
            auth_token=settings.turso_auth_token,
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


def result_to_dict(res: Any) -> dict[str, Any] | None:
    """Convert the first row of a ResultSet to a dict (or None)."""
    if not getattr(res, "rows", None):
        return None
    return dict(zip(res.columns, res.rows[0]))


def result_to_dicts(res: Any) -> list[dict[str, Any]]:
    """Convert all rows of a ResultSet to list[dict]."""
    if not getattr(res, "rows", None):
        return []
    return [dict(zip(res.columns, r)) for r in res.rows]


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
    await _apply_migration(client, applied, "20241003_01", _load_schema())
    await _apply_migration(client, applied, "20241003_02", _migration_02_statements())
    statements_03: list[str] = []
    if not await _has_column(client, "tiktok_scan_runs", "stop_reason"):
        statements_03.append("ALTER TABLE tiktok_scan_runs ADD COLUMN stop_reason TEXT")
    await _apply_migration(client, applied, "20241003_03", statements_03)
    statements_04: list[str] = []
    if not await _has_column(client, "tiktok_scan_runs", "scan_mode"):
        statements_04.append("ALTER TABLE tiktok_scan_runs ADD COLUMN scan_mode TEXT")
    statements_04.append("UPDATE tiktok_scan_runs SET scan_mode = 'initial' WHERE scan_mode IS NULL")
    await _apply_migration(client, applied, "20241003_04", statements_04)
    statements_05: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS youtube_oauth_states (
            state TEXT PRIMARY KEY,
            destination_id TEXT NOT NULL,
            pipeline_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            return_to TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS youtube_credentials (
            destination_id TEXT PRIMARY KEY,
            credentials_json TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
        """,
    ]
    if not await _has_column(client, "youtube_destinations", "connected"):
        statements_05.append("ALTER TABLE youtube_destinations ADD COLUMN connected INTEGER NOT NULL DEFAULT 0")
    if not await _has_column(client, "youtube_destinations", "connected_at"):
        statements_05.append("ALTER TABLE youtube_destinations ADD COLUMN connected_at TEXT")
    await _apply_migration(client, applied, "20241003_05", statements_05)
    statements_06: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS tiktok_ai_metadata (
            reel_db_id TEXT PRIMARY KEY,
            title TEXT,
            description TEXT,
            hashtags_json TEXT,
            model TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            source_hash TEXT,
            generated_at TEXT,
            last_error TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            next_retry_at TEXT,
            config_hash TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_tiktok_ai_metadata_next_retry ON tiktok_ai_metadata(next_retry_at)",
    ]
    await _apply_migration(client, applied, "20241003_06", statements_06)
    statements_07: list[str] = []
    for _col, _ddl in (
        ("youtube_title", "ALTER TABLE tiktok_publications ADD COLUMN youtube_title TEXT"),
        ("youtube_description", "ALTER TABLE tiktok_publications ADD COLUMN youtube_description TEXT"),
        ("youtube_hashtags_json", "ALTER TABLE tiktok_publications ADD COLUMN youtube_hashtags_json TEXT"),
        ("ai_model", "ALTER TABLE tiktok_publications ADD COLUMN ai_model TEXT"),
    ):
        if not await _has_column(client, "tiktok_publications", _col):
            statements_07.append(_ddl)
    await _apply_migration(client, applied, "20241003_07", statements_07)
    statements_08: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS tiktok_publish_schedules (
            id TEXT PRIMARY KEY,
            pipeline_id TEXT NOT NULL UNIQUE,
            timezone TEXT NOT NULL DEFAULT 'Asia/Ho_Chi_Minh',
            enabled INTEGER NOT NULL DEFAULT 0,
            max_daily_publish INTEGER NOT NULL DEFAULT 5,
            batch_time TEXT NOT NULL DEFAULT '06:00',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS tiktok_publish_schedule_slots (
            id TEXT PRIMARY KEY,
            schedule_id TEXT NOT NULL,
            weekday INTEGER NOT NULL,
            slot_time TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            UNIQUE(schedule_id, weekday, slot_time)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS tiktok_scheduler_runs (
            id TEXT PRIMARY KEY,
            pipeline_id TEXT NOT NULL,
            destination_id TEXT NOT NULL,
            scheduled_for TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            status TEXT NOT NULL DEFAULT 'queued',
            publication_id TEXT,
            reel_db_id TEXT,
            error TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            UNIQUE(pipeline_id, destination_id, scheduled_for)
        )
        """,
    ]
    await _apply_migration(client, applied, "20241003_08", statements_08)
    statements_09: list[str] = []
    if not await _has_column(client, "tiktok_publications", "scheduled_publish_at"):
        statements_09.append("ALTER TABLE tiktok_publications ADD COLUMN scheduled_publish_at TEXT")
    statements_09.append(
        """
        CREATE TABLE IF NOT EXISTS tiktok_scheduler_batches (
            id TEXT PRIMARY KEY,
            pipeline_id TEXT NOT NULL,
            destination_id TEXT NOT NULL,
            local_date TEXT NOT NULL,
            scheduled_batch_time TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            status TEXT NOT NULL DEFAULT 'queued',
            planned_count INTEGER NOT NULL DEFAULT 0,
            uploaded_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            UNIQUE(pipeline_id, destination_id, local_date)
        )
        """
    )
    await _apply_migration(client, applied, "20241003_09", statements_09)
    statements_10: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS tiktok_ai_settings (
            pipeline_id TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1,
            provider TEXT NOT NULL DEFAULT 'toolnet',
            model TEXT,
            system_prompt TEXT,
            title_prompt TEXT,
            description_prompt TEXT,
            hashtag_prompt TEXT,
            title_template TEXT,
            description_template TEXT,
            locked_hashtags_json TEXT NOT NULL DEFAULT '[]',
            language TEXT NOT NULL DEFAULT 'vi',
            max_hashtags INTEGER NOT NULL DEFAULT 10,
            include_emojis INTEGER NOT NULL DEFAULT 1,
            tone TEXT NOT NULL DEFAULT 'engaging',
            required_keywords TEXT NOT NULL DEFAULT '',
            forbidden_keywords TEXT NOT NULL DEFAULT '',
            config_hash TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
        """
    ]
    await _apply_migration(client, applied, "20241005_10", statements_10)
    statements_11: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS tiktok_publish_queue (
            id TEXT PRIMARY KEY,
            pipeline_id TEXT NOT NULL,
            destination_id TEXT NOT NULL,
            reel_db_id TEXT NOT NULL,
            publication_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            priority INTEGER NOT NULL DEFAULT 0,
            stage TEXT,
            error_code TEXT,
            error TEXT,
            queued_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            started_at TEXT,
            finished_at TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_tiktok_publish_queue_status_priority ON tiktok_publish_queue(status, priority, queued_at)",
        "CREATE INDEX IF NOT EXISTS idx_tiktok_publish_queue_pipeline ON tiktok_publish_queue(pipeline_id, status)",
    ]
    await _apply_migration(client, applied, "20241005_11", statements_11)
    statements_12: list[str] = []
    if not await _has_column(client, "tiktok_reels", "ai_claimed_at"):
        statements_12.append("ALTER TABLE tiktok_reels ADD COLUMN ai_claimed_at TEXT")
    await _apply_migration(client, applied, "20241005_12", statements_12)
    statements_14: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS system_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
        """,
    ]
    await _apply_migration(client, applied, "20241005_14", statements_14)
    statements_15: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS tiktok_manual_publications (
            id TEXT PRIMARY KEY,
            destination_id TEXT NOT NULL,
            pipeline_id TEXT NOT NULL,
            source_url TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            caption TEXT,
            thumbnail_url TEXT,
            duration REAL,
            youtube_title TEXT,
            youtube_description TEXT,
            youtube_hashtags_json TEXT,
            visibility TEXT NOT NULL DEFAULT 'public',
            publish_at TEXT,
            status TEXT NOT NULL DEFAULT 'queued',
            stage TEXT,
            youtube_video_id TEXT,
            error_code TEXT,
            error TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_tiktok_manual_pub_destination ON tiktok_manual_publications(destination_id, status, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_tiktok_manual_pub_source ON tiktok_manual_publications(destination_id, source_hash)",
        "CREATE INDEX IF NOT EXISTS idx_tiktok_manual_pub_status ON tiktok_manual_publications(status, created_at)",
    ]
    await _apply_migration(client, applied, "20241005_15", statements_15)
    statements_17: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS tiktok_quota_pauses (
            pipeline_id TEXT PRIMARY KEY,
            paused_until TEXT NOT NULL,
            reason TEXT,
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_tiktok_quota_pauses_until ON tiktok_quota_pauses(paused_until)",
    ]
    await _apply_migration(client, applied, "20261020_20", statements_17)
    statements_21: list[str] = [
        """
        UPDATE tiktok_publish_queue
        SET status = 'failed', stage = 'superseded',
            error_code = 'DUPLICATE_JOB',
            error = 'Superseded by another active job for this publication',
            finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                    ROW_NUMBER() OVER (
                        PARTITION BY publication_id
                        ORDER BY CASE status WHEN 'processing' THEN 0 ELSE 1 END,
                                 queued_at ASC, id ASC
                    ) AS rn
                FROM tiktok_publish_queue
                WHERE status IN ('queued', 'processing')
            )
            WHERE rn > 1
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_tiktok_publish_queue_active_publication "
        "ON tiktok_publish_queue(publication_id) "
        "WHERE status IN ('queued', 'processing')",
        """
        UPDATE tiktok_publications
        SET status = 'scheduled', last_error = NULL,
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        WHERE status = 'failed'
        AND last_error LIKE 'CLAIM_LOST:%'
        AND youtube_video_id IS NOT NULL
        AND EXISTS (
            SELECT 1 FROM tiktok_reels r
            WHERE r.id = tiktok_publications.reel_db_id
            AND r.status = 'scheduled'
            AND r.youtube_video_id = tiktok_publications.youtube_video_id
        )
        """,
    ]
    await _apply_migration(client, applied, "20261021_21", statements_21)
    statements_22: list[str] = [
        "CREATE INDEX IF NOT EXISTS idx_tiktok_reels_source_status_discovered "
        "ON tiktok_reels(source_id, status, discovered_at DESC, id)",
    ]
    await _apply_migration(client, applied, "20261024_22", statements_22)

    statements_23: list[str] = []
    if not await _has_column(client, "tiktok_ai_settings", "provider"):
        statements_23.append("ALTER TABLE tiktok_ai_settings ADD COLUMN provider TEXT NOT NULL DEFAULT 'toolnet'")
    if not await _has_column(client, "tiktok_ai_settings", "title_prompt"):
        statements_23.append("ALTER TABLE tiktok_ai_settings ADD COLUMN title_prompt TEXT")
    if not await _has_column(client, "tiktok_ai_settings", "description_prompt"):
        statements_23.append("ALTER TABLE tiktok_ai_settings ADD COLUMN description_prompt TEXT")
    if not await _has_column(client, "tiktok_ai_settings", "hashtag_prompt"):
        statements_23.append("ALTER TABLE tiktok_ai_settings ADD COLUMN hashtag_prompt TEXT")
    if not await _has_column(client, "tiktok_ai_settings", "max_hashtags"):
        statements_23.append("ALTER TABLE tiktok_ai_settings ADD COLUMN max_hashtags INTEGER NOT NULL DEFAULT 10")
    if not await _has_column(client, "tiktok_ai_settings", "include_emojis"):
        statements_23.append("ALTER TABLE tiktok_ai_settings ADD COLUMN include_emojis INTEGER NOT NULL DEFAULT 1")
    if not await _has_column(client, "tiktok_ai_settings", "tone"):
        statements_23.append("ALTER TABLE tiktok_ai_settings ADD COLUMN tone TEXT NOT NULL DEFAULT 'engaging'")
    if not await _has_column(client, "tiktok_ai_settings", "required_keywords"):
        statements_23.append("ALTER TABLE tiktok_ai_settings ADD COLUMN required_keywords TEXT NOT NULL DEFAULT ''")
    if not await _has_column(client, "tiktok_ai_settings", "forbidden_keywords"):
        statements_23.append("ALTER TABLE tiktok_ai_settings ADD COLUMN forbidden_keywords TEXT NOT NULL DEFAULT ''")
    await _apply_migration(client, applied, "20261026_23", statements_23)


async def _apply_migration(
    client: Any, applied: set, version: str, statements: list[str]
) -> None:
    if version in applied:
        logger.debug("migration %s already applied, skipping", version)
        return
    try:
        for sql_stmt in statements:
            if sql_stmt.strip():
                await client.execute(sql_stmt)
        await client.execute(
            "INSERT INTO schema_migrations (version) VALUES (:version)",
            {"version": version},
        )
    except Exception as exc:
        raise RuntimeError(f"migration {version} failed: {exc}") from exc
    logger.info("migration %s applied", version)


async def _has_column(client: Any, table: str, column: str) -> bool:
    try:
        info = await client.execute(f"PRAGMA table_info({table})")
    except Exception:
        return False
    return any(len(row) > 1 and row[1] == column for row in (info.rows or []))


def _load_schema() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS tiktok_pipelines (
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
        CREATE TABLE IF NOT EXISTS tiktok_sources (
            id TEXT PRIMARY KEY,
            pipeline_id TEXT NOT NULL,
            username TEXT NOT NULL,
            display_name TEXT,
            source_url TEXT,
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
        CREATE TABLE IF NOT EXISTS tiktok_reels (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            reel_id TEXT NOT NULL,
            reel_url TEXT,
            caption TEXT,
            thumbnail_url TEXT,
            source_published_at TEXT,
            duration INTEGER,
            play_count INTEGER,
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
            connected INTEGER NOT NULL DEFAULT 0,
            connected_at TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS tiktok_publications (
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
        CREATE TABLE IF NOT EXISTS tiktok_scan_runs (
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
        "CREATE INDEX IF NOT EXISTS idx_tiktok_reels_source_id_status ON tiktok_reels(source_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_tiktok_reels_status_discovered_at ON tiktok_reels(status, discovered_at)",
        "CREATE INDEX IF NOT EXISTS idx_tiktok_sources_pipeline_id ON tiktok_sources(pipeline_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_tiktok_sources_pipeline_username ON tiktok_sources(pipeline_id, username)",
        "CREATE INDEX IF NOT EXISTS idx_tiktok_publications_destination_id_status ON tiktok_publications(destination_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_tiktok_scan_runs_source_id_started_at ON tiktok_scan_runs(source_id, started_at)",
    ]


def _migration_02_statements() -> list[str]:
    # page_name was already nullable in tiktok schema; keep this migration
    # entry for version-tracking parity with facebook. No-op for new deploys.
    return []
