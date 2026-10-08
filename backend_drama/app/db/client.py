"""SQLite client with versioned, idempotent migrations.

Phase 1 runs on local SQLite (stdlib only, no driver needed). A non-file
DRAMA_TURSO_URL is reserved for shared libSQL storage in a later phase;
until then the service boots with db=not_configured for DB-backed routes
while /health stays green.
"""

import logging
import re
import sqlite3
import threading
import concurrent.futures
import time
from pathlib import Path
from typing import Any

from app.config import settings


def _to_positional(sql: str, parameters: Any) -> tuple[str, list]:
    """Rewrite :named params to positional ? for the hrana client.

    The repo layer was written against sqlite3 named style; the remote
    client only binds positionally. Dicts convert in first-appearance
    order; tuples/lists pass through unchanged.
    """
    if isinstance(parameters, dict):
        names = re.findall(r":([A-Za-z_][A-Za-z0-9_]*)", sql)
        try:
            args = [parameters[name] for name in names]
        except KeyError as exc:
            raise RuntimeError(f"Missing SQL parameter: {exc}") from exc
        query = re.sub(r":[A-Za-z_][A-Za-z0-9_]*", "?", sql)
        return query, args
    return sql, list(parameters or [])

try:
    import libsql_client
except ImportError:
    libsql_client = None

logger = logging.getLogger("backend-drama-db")

_lock = threading.Lock()
_client_instance = None
_db_status = "not_configured"


class CursorWrapper:
    def __init__(self, result_set: Any | None):
        if result_set is not None and hasattr(result_set, 'rows'):
            self.rows = result_set.rows
        else:
            self.rows = []
        self._idx = 0

    def fetchone(self) -> Any | None:
        if self._idx < len(self.rows):
            r = self.rows[self._idx]
            self._idx += 1
            return r
        return None

    def fetchall(self) -> list[Any]:
        r = self.rows[self._idx:]
        self._idx = len(self.rows)
        return r


class BaseDatabase:
    def execute(self, sql: str, parameters: tuple | list = ()) -> Any:
        raise NotImplementedError

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


class LocalSQLiteDatabase(BaseDatabase):
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")

    def execute(self, sql: str, parameters: tuple | list = ()) -> Any:
        return self.conn.execute(sql, parameters)

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


class RemoteTursoDatabase(BaseDatabase):
    def __init__(self, url: str, token: str):
        if libsql_client is None:
            raise RuntimeError("libsql_client package is not installed.")
        self.url = url
        self.token = token
        # Client automatically uses http connection pooling and handles keepalive.
        # token is passed securely to auth_token and not logged.
        self._client = libsql_client.create_client_sync(self.url, auth_token=self.token)

    def execute(self, sql: str, parameters: tuple | list | dict = ()) -> Any:
        try:
            query, args = _to_positional(sql, parameters)
            rs = self._client.execute(query, args)
            return CursorWrapper(rs)
        except libsql_client.LibsqlError as e:
            logger.error("Turso LibSQL error: %s", type(e).__name__)
            raise RuntimeError(f"Database error: {e}") from e

    def commit(self) -> None:
        pass

    def close(self) -> None:
        self._client.close()


def db_configured() -> tuple[bool, str]:
    global _db_status
    url = (settings.DRAMA_TURSO_URL or "").strip()
    if not url:
        return True, _db_status if _db_status != "not_configured" else "sqlite"
    if url.startswith("file:"):
        return True, _db_status if _db_status != "not_configured" else "sqlite"
    
    if _db_status == "not_configured":
        return True, "turso"
    return (_db_status == "ok"), _db_status


def get_client() -> BaseDatabase:
    global _client_instance
    ok, db_type = db_configured()
    if not ok and _db_status not in ("ok", "not_configured", "sqlite", "turso"):
        raise RuntimeError(f"Database unavailable: {_db_status}")
        
    with _lock:
        if _client_instance is None:
            url = (settings.DRAMA_TURSO_URL or "").strip()
            if not url or url.startswith("file:"):
                if url.startswith("file:"):
                    path = Path(url[len("file:"):])
                else:
                    path = Path(settings.DRAMA_DB_PATH)
                _client_instance = LocalSQLiteDatabase(path)
            else:
                if url.startswith("libsql://"):
                    url = "https://" + url[len("libsql://"):]
                
                token = settings.DRAMA_TURSO_TOKEN or ""
                _client_instance = RemoteTursoDatabase(url, token)
        return _client_instance


def reset_client() -> None:
    global _client_instance, _db_status
    with _lock:
        if _client_instance is not None:
            try:
                _client_instance.close()
            except Exception:
                pass
            _client_instance = None
        _db_status = "not_configured"


def verify_connection() -> str:
    url = (settings.DRAMA_TURSO_URL or "").strip()
    if not url or url.startswith("file:"):
        return "PASS"

    def _do_check():
        for attempt in range(2):
            try:
                client = get_client()
                client.execute("SELECT 1")
                return "PASS"
            except Exception as e:
                msg = str(e).lower()
                if "400" in msg or "401" in msg or "403" in msg or "auth" in msg:
                    return "AUTH_FAILED"
                if attempt == 1:
                    return "NETWORK_ERROR"
                time.sleep(1)
        return "NETWORK_ERROR"

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_do_check)
            return future.result(timeout=15.0)
    except concurrent.futures.TimeoutError:
        return "TIMEOUT"
    except Exception:
        return "NETWORK_ERROR"


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
    (
        "drama_002",
        [
            """
            CREATE TABLE IF NOT EXISTS drama_discovery_cache (
                provider TEXT NOT NULL,
                external_series_id TEXT NOT NULL,
                title TEXT,
                description TEXT,
                thumbnail_url TEXT,
                total_episodes INTEGER,
                fetched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                PRIMARY KEY (provider, external_series_id)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_discovery_cache_fetched ON drama_discovery_cache(fetched_at)",
            "CREATE INDEX IF NOT EXISTS idx_discovery_cache_provider ON drama_discovery_cache(provider)",
        ],
    ),
    (
        "drama_003",
        [
            """
            CREATE TABLE IF NOT EXISTS drama_discovery_snapshots (
                cache_key TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                query TEXT NOT NULL DEFAULT '',
                limit_value INTEGER NOT NULL,
                items_json TEXT NOT NULL,
                provider_status_json TEXT,
                fetched_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_discovery_snapshots_provider ON drama_discovery_snapshots(provider)",
            "CREATE INDEX IF NOT EXISTS idx_discovery_snapshots_updated ON drama_discovery_snapshots(updated_at)",
        ],
    ),
    (
        "drama_004",
        [
            """
            CREATE TABLE IF NOT EXISTS drama_episode_asr (
                episode_id TEXT PRIMARY KEY,
                series_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                source_language TEXT,
                engine TEXT NOT NULL DEFAULT 'jianying',
                srt_text TEXT,
                segment_count INTEGER,
                duration_ms INTEGER,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_error_code TEXT,
                last_error_message TEXT,
                started_at TEXT,
                completed_at TEXT,
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_episode_asr_series ON drama_episode_asr(series_id, status)",
        ],
    ),
    (
        "drama_005",
        [
            """
            CREATE TABLE IF NOT EXISTS drama_pipeline_settings (
                pipeline_id TEXT PRIMARY KEY,
                processing_mode TEXT NOT NULL DEFAULT 'direct_merge',
                merge_all_episodes INTEGER NOT NULL DEFAULT 1,
                episodes_per_video INTEGER,
                target_language TEXT,
                subtitle_enabled INTEGER NOT NULL DEFAULT 1,
                tts_enabled INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS drama_series_jobs (
                id TEXT PRIMARY KEY,
                pipeline_id TEXT NOT NULL,
                series_id TEXT NOT NULL,
                processing_mode TEXT NOT NULL DEFAULT 'direct_merge',
                chunk_index INTEGER NOT NULL DEFAULT 0,
                episode_start INTEGER,
                episode_end INTEGER,
                status TEXT NOT NULL DEFAULT 'queued',
                stage TEXT,
                downloaded_episode_ids_json TEXT NOT NULL DEFAULT '[]',
                output_path TEXT,
                youtube_video_id TEXT,
                last_error_code TEXT,
                last_error_message TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_series_jobs_series ON drama_series_jobs(series_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_series_jobs_pipeline ON drama_series_jobs(pipeline_id, status)",
        ],
    ),
    (
        "drama_006",
        [
            "ALTER TABLE drama_pipeline_settings ADD COLUMN template_enabled INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE drama_pipeline_settings ADD COLUMN template_id TEXT",
            "ALTER TABLE drama_pipeline_settings ADD COLUMN template_mode TEXT",
            "ALTER TABLE drama_pipeline_settings ADD COLUMN youtube_destination_id TEXT",
            "ALTER TABLE drama_pipeline_settings ADD COLUMN auto_publish INTEGER NOT NULL DEFAULT 1",
            """
            CREATE TABLE IF NOT EXISTS drama_templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                asset_url TEXT NOT NULL,
                canvas_width INTEGER NOT NULL DEFAULT 1280,
                canvas_height INTEGER NOT NULL DEFAULT 720,
                content_x INTEGER NOT NULL DEFAULT 0,
                content_y INTEGER NOT NULL DEFAULT 0,
                content_width INTEGER NOT NULL DEFAULT 1280,
                content_height INTEGER NOT NULL DEFAULT 720,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )
            """,
            "ALTER TABLE drama_series_jobs ADD COLUMN upload_progress REAL",
            "ALTER TABLE drama_series_jobs ADD COLUMN template_id TEXT",
        ],
    ),
    (
        "drama_007",
        [
            """
            CREATE TABLE IF NOT EXISTS drama_episode_tasks (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                episode_id TEXT NOT NULL,
                episode_number INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                render_progress REAL,
                segment_path TEXT,
                segment_bytes INTEGER,
                duration REAL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_error_code TEXT,
                last_error_message TEXT,
                started_at TEXT,
                completed_at TEXT,
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                UNIQUE(job_id, episode_id)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_ep_tasks_job ON drama_episode_tasks(job_id, status)",
        ],
    ),
    (
        "drama_008",
        [
            """
            CREATE TABLE IF NOT EXISTS drama_youtube_destinations (
                id TEXT PRIMARY KEY,
                pipeline_id TEXT NOT NULL,
                channel_id TEXT,
                channel_title TEXT,
                channel_thumbnail TEXT,
                visibility TEXT NOT NULL DEFAULT 'public',
                enabled INTEGER NOT NULL DEFAULT 1,
                connected INTEGER NOT NULL DEFAULT 0,
                connected_at TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS drama_youtube_credentials (
                destination_id TEXT PRIMARY KEY,
                channel_id TEXT,
                refresh_token_encrypted TEXT,
                token_uri TEXT NOT NULL DEFAULT 'https://oauth2.googleapis.com/token',
                status TEXT NOT NULL DEFAULT 'active',
                connected_at TEXT,
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS drama_oauth_states (
                state TEXT PRIMARY KEY,
                destination_id TEXT NOT NULL,
                pipeline_id TEXT NOT NULL,
                return_to TEXT,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_yt_dest_pipeline ON drama_youtube_destinations(pipeline_id, connected)",
        ],
    ),
]


def migrate() -> list[str]:
    """Apply pending migrations in order. Idempotent. Returns applied versions."""
    global _db_status
    
    status = verify_connection()
    if status != "PASS":
        logger.error("Database connection verification failed: %s", status)
        _db_status = status
        raise RuntimeError(f"Database unavailable: {status}")
        
    conn = get_client()
    applied: list[str] = []
    with _lock:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version TEXT PRIMARY KEY, "
            "applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')))"
        )
        # Handle dict-like row access for both sqlite3.Row and libsql_client.Row
        have = set()
        for r in conn.execute("SELECT version FROM schema_migrations").fetchall():
            have.add(r[0])
            
        for version, statements in MIGRATIONS:
            if version in have:
                continue
            for sql in statements:
                try:
                    conn.execute(sql)
                except Exception as exc:
                    # Tolerate re-runs after a partial apply (e.g. a column
                    # that already exists from an earlier attempt).
                    if "duplicate column name" in str(exc).lower():
                        continue
                    raise
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
            )
            conn.commit()
            applied.append(version)
            
    if applied:
        logger.info("drama migrations applied: %s", applied)
    _db_status = "ok"
    return applied
