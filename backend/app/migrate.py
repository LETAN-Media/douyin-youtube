import logging
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine as default_engine
from app.models import (
    Base,
    Destination,
    DouyinSession,
    DouyinSource,
    DouyinVideo,
    Pipeline,
    PipelineSource,
    PlatformAccount,
    Publication,
    User,
    UserSession,
    Workspace,
    WorkspaceMember,
    YouTubeChannelAnalyticsDaily,
    YouTubeChannelDNA,
    YouTubeComment,
    YouTubeContentFingerprint,
    YouTubeDailyPublishOverride,
    YouTubeDNASuggestion,
    YouTubePerformanceSnapshot,
    YouTubeResearchItem,
    YouTubeResearchRun,
    YouTubeVideoAnalyticsDaily,
)

logger = logging.getLogger("douyin-youtube-migrate")

DEFAULT_PIPELINE_NAME = "Vibe Men World"
DEFAULT_PIPELINE_SLUG = "vibe-men-world"
DEFAULT_PIPELINE_NICHE = "attractive men, male aesthetic, fitness and men's lifestyle"
DEFAULT_PIPELINE_LANGUAGE = "en"
DEFAULT_PIPELINE_FIXED_HASHTAGS = ["#handsomeboy", "#maleaesthetic"]
DEFAULT_PIPELINE_ADAPTIVE_HASHTAGS = [
    "#fitboy",
    "#muscle",
    "#gymboy",
    "#sixpack",
    "#mensfashion",
    "#mensstyle",
    "#broadshoulders",
]
DEFAULT_PIPELINE_DEFAULT_PRIVACY = "public"
ADMIN_WORKSPACE_NAME = "Admin Workspace"

_TENANT_TABLES = [
    "pipelines",
    "destinations",
    "pipeline_sources",
    "douyin_sources",
    "douyin_videos",
    "publications",
    "video_jobs",
    "youtube_comments",
    "youtube_channel_analytics_daily",
    "youtube_video_analytics_daily",
    "youtube_research_runs",
    "youtube_research_items",
    "youtube_channel_dna",
    "youtube_content_fingerprints",
    "youtube_performance_snapshots",
    "youtube_dna_suggestions",
    "youtube_daily_publish_overrides",
    "oauth_states",
]


# =====================================================================
# BƯỚC 1: INSTRUMENTATION HELPER
# =====================================================================

@contextmanager
def log_step(name: str) -> Generator[None, None, None]:
    """Logs migration steps with format:
    [MIGRATION START] <step>
    [MIGRATION OK] <step> <duration_ms>ms
    [MIGRATION FAILED] <step> <exception>
    """
    print(f"[MIGRATION START] {name}", flush=True)
    logger.info("[MIGRATION START] %s", name)
    t0 = time.perf_counter()
    try:
        yield
        duration_ms = (time.perf_counter() - t0) * 1000.0
        print(f"[MIGRATION OK] {name} {duration_ms:.2f}ms", flush=True)
        logger.info("[MIGRATION OK] %s %.2fms", name, duration_ms)
    except Exception as exc:
        duration_ms = (time.perf_counter() - t0) * 1000.0
        print(f"[MIGRATION FAILED] {name} {exc}", flush=True)
        logger.error("[MIGRATION FAILED] %s %s (after %.2fms)", name, exc, duration_ms)
        raise


# =====================================================================
# BƯỚC 3 & 5: DIALECT DETECTION & IN-MEMORY SCHEMA CACHE
# =====================================================================

def is_sqlite_dialect(engine_or_conn: Any) -> bool:
    dialect_name = getattr(getattr(engine_or_conn, "dialect", None), "name", "")
    return dialect_name in ("sqlite", "libsql") or getattr(settings, "database_provider", "") == "turso"


def _timestamp_type(engine_or_conn: Any) -> str:
    return "TEXT" if is_sqlite_dialect(engine_or_conn) else "TIMESTAMPTZ"


def _now_expr(engine_or_conn: Any) -> str:
    return "CURRENT_TIMESTAMP" if is_sqlite_dialect(engine_or_conn) else "NOW()"


class SchemaCache:
    """Caches tables, columns, and indexes in memory for a single migration run.
    Eliminates hundreds of remote network roundtrips over Turso / libSQL.
    """

    def __init__(self, conn: Any, is_sqlite: bool) -> None:
        self.is_sqlite = is_sqlite
        self.tables: set[str] = set()
        self.columns: dict[str, set[str]] = {}
        self.indexes: dict[str, set[str]] = {}
        self._load(conn)

    def _load(self, conn: Any) -> None:
        if self.is_sqlite:
            # 1 query for all tables, views, and indexes
            rows = conn.execute(
                text("SELECT type, name, tbl_name FROM sqlite_master WHERE type IN ('table', 'index')")
            ).fetchall()
            for r_type, r_name, tbl_name in rows:
                if r_type == "table":
                    self.tables.add(r_name)
                    if r_name not in self.columns:
                        self.columns[r_name] = set()
                    if r_name not in self.indexes:
                        self.indexes[r_name] = set()
                elif r_type == "index":
                    if tbl_name not in self.indexes:
                        self.indexes[tbl_name] = set()
                    self.indexes[tbl_name].add(r_name)

            # Inspect columns for existing tables
            for tbl in list(self.tables):
                col_rows = conn.execute(text(f'PRAGMA table_info("{tbl}")')).fetchall()
                self.columns[tbl] = {r[1] for r in col_rows}
        else:
            # PostgreSQL information_schema
            tbl_rows = conn.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
            ).fetchall()
            for (t_name,) in tbl_rows:
                self.tables.add(t_name)
                self.columns[t_name] = set()
                self.indexes[t_name] = set()

            col_rows = conn.execute(
                text("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'")
            ).fetchall()
            for t_name, c_name in col_rows:
                if t_name in self.columns:
                    self.columns[t_name].add(c_name)

            idx_rows = conn.execute(
                text("SELECT tablename, indexname FROM pg_indexes WHERE schemaname = 'public'")
            ).fetchall()
            for t_name, i_name in idx_rows:
                if t_name in self.indexes:
                    self.indexes[t_name].add(i_name)

    def table_exists(self, table_name: str) -> bool:
        return table_name in self.tables

    def column_exists(self, table_name: str, column_name: str) -> bool:
        return column_name in self.columns.get(table_name, set())

    def index_exists(self, table_name: str, index_name: str) -> bool:
        return index_name in self.indexes.get(table_name, set())

    def add_table(self, table_name: str, cols: list[str] | None = None) -> None:
        self.tables.add(table_name)
        self.columns[table_name] = set(cols or [])
        if table_name not in self.indexes:
            self.indexes[table_name] = set()

    def add_column(self, table_name: str, column_name: str) -> None:
        if table_name not in self.columns:
            self.columns[table_name] = set()
        self.columns[table_name].add(column_name)

    def add_index(self, table_name: str, index_name: str) -> None:
        if table_name not in self.indexes:
            self.indexes[table_name] = set()
        self.indexes[table_name].add(index_name)


# Global reference to active cache during a run (for backward compat helpers)
_active_cache: SchemaCache | None = None


# Backward-compatible helper functions
def table_exists(connection: Any, table_name: str) -> bool:
    if _active_cache is not None:
        return _active_cache.table_exists(table_name)
    if is_sqlite_dialect(connection):
        res = connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name = :name"),
            {"name": table_name},
        ).fetchone()
        return res is not None
    inspector = inspect(connection)
    return inspector.has_table(table_name)


def column_exists(connection: Any, table_name: str, column_name: str) -> bool:
    if _active_cache is not None:
        return _active_cache.column_exists(table_name, column_name)
    if is_sqlite_dialect(connection):
        res = connection.execute(text(f'PRAGMA table_info("{table_name}")')).fetchall()
        return column_name in [r[1] for r in res]
    inspector = inspect(connection)
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


# =====================================================================
# BƯỚC 4: SCHEMA MIGRATIONS TABLE
# =====================================================================

def ensure_schema_migrations_table(engine: Any) -> None:
    with log_step("ensure_schema_migrations_table"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS schema_migrations ("
                    "version TEXT PRIMARY KEY, "
                    "applied_at TEXT NOT NULL"
                    ")"
                )
            )


def get_applied_migrations(engine: Any) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT version FROM schema_migrations")).fetchall()
        return {r[0] for r in rows}


def record_migration(engine: Any, version: str) -> None:
    now_str = datetime.now(timezone.utc).isoformat()
    is_sqlite = is_sqlite_dialect(engine)
    with engine.begin() as conn:
        if is_sqlite:
            conn.execute(
                text("INSERT OR REPLACE INTO schema_migrations (version, applied_at) VALUES (:v, :t)"),
                {"v": version, "t": now_str},
            )
        else:
            conn.execute(
                text(
                    "INSERT INTO schema_migrations (version, applied_at) "
                    "VALUES (:v, :t) ON CONFLICT (version) DO NOTHING"
                ),
                {"v": version, "t": now_str},
            )


# =====================================================================
# BƯỚC 6: SAFE GUARDED BACKFILL HELPER
# =====================================================================

def safe_backfill_update(
    engine: Any,
    step_name: str,
    check_sql: str,
    update_sql: str,
    params: dict[str, Any] | None = None,
) -> int:
    """Ensures large UPDATEs only run if there are rows needing backfill.
    SELECT COUNT(*) first; if 0, skips completely.
    """
    params = params or {}
    with log_step(step_name):
        with engine.connect() as conn:
            cnt = conn.execute(text(check_sql), params).fetchone()[0]
        if cnt == 0:
            logger.info("Skipped %s: 0 rows to update", step_name)
            return 0
        with engine.begin() as conn:
            res = conn.execute(text(update_sql), params)
            updated = res.rowcount if res.rowcount is not None and res.rowcount >= 0 else cnt
            logger.info("Updated %d rows for %s", updated, step_name)
            return updated


# =====================================================================
# MIGRATION DEFINITIONS (ISOLATED SHORT TRANSACTIONS)
# =====================================================================

class MigrationDefinition:
    def __init__(
        self,
        version: str,
        description: str,
        verify_fn: Callable[[SchemaCache, Any], bool],
        apply_fn: Callable[[SchemaCache, Any], None],
    ) -> None:
        self.version = version
        self.description = description
        self.verify_fn = verify_fn
        self.apply_fn = apply_fn


# --- Migration 001: Core Tables ---
def _verify_001(cache: SchemaCache, engine: Any) -> bool:
    required = {
        "pipelines",
        "douyin_sources",
        "douyin_videos",
        "destinations",
        "publications",
        "douyin_sessions",
        "platform_accounts",
        "pipeline_sources",
    }
    return required.issubset(cache.tables)


def _apply_001(cache: SchemaCache, engine: Any) -> None:
    models_to_check = [
        ("pipelines", Pipeline),
        ("douyin_sources", DouyinSource),
        ("douyin_videos", DouyinVideo),
        ("destinations", Destination),
        ("publications", Publication),
        ("douyin_sessions", DouyinSession),
        ("platform_accounts", PlatformAccount),
        ("pipeline_sources", PipelineSource),
    ]
    for tbl_name, model_cls in models_to_check:
        if not cache.table_exists(tbl_name):
            with log_step(f"create_table_{tbl_name}"):
                with engine.begin() as conn:
                    Base.metadata.create_all(bind=conn, tables=[model_cls.__table__])
                cache.add_table(tbl_name, [c.name for c in model_cls.__table__.columns])


# --- Migration 002: Analytics Tables ---
def _verify_002(cache: SchemaCache, engine: Any) -> bool:
    required = {
        "youtube_channel_analytics_daily",
        "youtube_video_analytics_daily",
        "youtube_research_runs",
        "youtube_research_items",
        "youtube_channel_dna",
        "youtube_content_fingerprints",
        "youtube_performance_snapshots",
        "youtube_dna_suggestions",
        "youtube_daily_publish_overrides",
    }
    return required.issubset(cache.tables)


def _apply_002(cache: SchemaCache, engine: Any) -> None:
    models = [
        YouTubeChannelAnalyticsDaily,
        YouTubeVideoAnalyticsDaily,
        YouTubeResearchRun,
        YouTubeResearchItem,
        YouTubeChannelDNA,
        YouTubeContentFingerprint,
        YouTubePerformanceSnapshot,
        YouTubeDNASuggestion,
        YouTubeDailyPublishOverride,
    ]
    for model_cls in models:
        tbl_name = model_cls.__table__.name
        if not cache.table_exists(tbl_name):
            with log_step(f"create_table_{tbl_name}"):
                with engine.begin() as conn:
                    Base.metadata.create_all(bind=conn, tables=[model_cls.__table__])
                cache.add_table(tbl_name, [c.name for c in model_cls.__table__.columns])


# --- Migration 003: Core Columns ---
def _verify_003(cache: SchemaCache, engine: Any) -> bool:
    checks = [
        ("destinations", "research_region"),
        ("douyin_sources", "platform"),
        ("douyin_sources", "avatar_url"),
        ("douyin_sources", "priority"),
        ("platform_accounts", "needs_reauth"),
        ("pipeline_sources", "last_error"),
        ("video_jobs", "pipeline_id"),
        ("video_jobs", "source_video_id"),
        ("video_jobs", "schedule_slot_key"),
        ("video_jobs", "destination_id"),
        ("video_jobs", "publication_id"),
        ("pipelines", "youtube_credentials"),
        ("pipelines", "youtube_connected"),
        ("pipelines", "youtube_channel_id"),
        ("pipelines", "youtube_channel_title"),
        ("oauth_states", "pipeline_id"),
        ("oauth_states", "destination_id"),
    ]
    return all(cache.column_exists(tbl, col) for tbl, col in checks)


def _apply_003(cache: SchemaCache, engine: Any) -> None:
    is_sqlite = is_sqlite_dialect(engine)

    # Bigint column types for PostgreSQL only (SQLite INTEGER is dynamically typed up to 64-bit)
    if not is_sqlite:
        for _tbl, _col in [
            ("youtube_channel_analytics_daily", "views"),
            ("youtube_channel_analytics_daily", "likes"),
            ("youtube_channel_analytics_daily", "comments"),
            ("youtube_channel_analytics_daily", "shares"),
            ("youtube_channel_analytics_daily", "subs_gained"),
            ("youtube_channel_analytics_daily", "subs_lost"),
            ("youtube_video_analytics_daily", "views"),
            ("youtube_video_analytics_daily", "likes"),
            ("youtube_video_analytics_daily", "comments"),
            ("youtube_video_analytics_daily", "subs_gained"),
            ("youtube_research_items", "views"),
        ]:
            if cache.table_exists(_tbl) and cache.column_exists(_tbl, _col):
                with log_step(f"pg_bigint_{_tbl}_{_col}"):
                    try:
                        with engine.begin() as conn:
                            conn.execute(text(f"ALTER TABLE {_tbl} ALTER COLUMN {_col} TYPE BIGINT"))
                    except Exception as e:
                        logger.info("bigint %s.%s skipped: %s", _tbl, _col, e)

    cols_to_add = [
        ("destinations", "research_region", "VARCHAR(10) DEFAULT 'VN'"),
        ("douyin_sources", "platform", "VARCHAR(20) DEFAULT 'douyin'"),
        ("douyin_sources", "avatar_url", "TEXT"),
        ("douyin_sources", "priority", "INTEGER DEFAULT 0"),
        ("platform_accounts", "needs_reauth", "BOOLEAN DEFAULT FALSE"),
        ("pipeline_sources", "last_error", "TEXT"),
        ("video_jobs", "pipeline_id", "VARCHAR(36)"),
        ("video_jobs", "source_video_id", "VARCHAR(200)"),
        ("video_jobs", "schedule_slot_key", "VARCHAR(100)"),
        ("video_jobs", "destination_id", "VARCHAR(36)"),
        ("video_jobs", "publication_id", "VARCHAR(36)"),
        ("pipelines", "youtube_credentials", "TEXT"),
        ("pipelines", "youtube_connected", "BOOLEAN DEFAULT FALSE"),
        ("pipelines", "youtube_channel_id", "VARCHAR(200)"),
        ("pipelines", "youtube_channel_title", "VARCHAR(300)"),
        ("oauth_states", "pipeline_id", "VARCHAR(36)"),
        ("oauth_states", "destination_id", "VARCHAR(36)"),
    ]
    for tbl, col, col_type in cols_to_add:
        if cache.table_exists(tbl) and not cache.column_exists(tbl, col):
            with log_step(f"add_col_{tbl}_{col}"):
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN {col} {col_type}"))
                cache.add_column(tbl, col)

    # FK constraint: PostgreSQL only (SQLite foreign keys are defined at table creation)
    if not is_sqlite and cache.table_exists("video_jobs") and cache.table_exists("publications"):
        with log_step("pg_add_fk_video_jobs_publication"):
            try:
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            "ALTER TABLE video_jobs "
                            "ADD CONSTRAINT fk_video_jobs_publication_id "
                            "FOREIGN KEY (publication_id) "
                            "REFERENCES publications(id) "
                            "ON DELETE SET NULL"
                        )
                    )
            except Exception:
                logger.info("FK video_jobs.publication_id already exists or skipped")

    # One-time per-source cookie -> global PlatformAccount
    with log_step("migrate_douyin_cookie_to_platform_account"):
        try:
            with engine.connect() as conn:
                has_cookie = conn.execute(
                    text("SELECT cookie_encrypted FROM douyin_sources WHERE cookie_encrypted IS NOT NULL LIMIT 1")
                ).fetchone()
                exists = conn.execute(
                    text("SELECT 1 FROM platform_accounts WHERE platform='douyin' LIMIT 1")
                ).fetchone()

            if has_cookie is not None and exists is None:
                import uuid as _uuid
                now_fn = _now_expr(engine)
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            "INSERT INTO platform_accounts (id, platform, display_name, status, credentials_encrypted, needs_reauth, created_at, updated_at) "
                            f"VALUES (:id, 'douyin', 'Douyin', 'connected', :creds, FALSE, {now_fn}, {now_fn})"
                        ),
                        {"id": str(_uuid.uuid4()), "creds": has_cookie[0]},
                    )
        except Exception as exc:
            logger.warning("PlatformAccount cookie migration skipped: %s", exc)


# --- Migration 004: Destinations Scheduler Columns ---
def _verify_004(cache: SchemaCache, engine: Any) -> bool:
    cols = ["last_scheduler_check_at", "last_cycle_at", "last_job_created_at", "last_skip_reason"]
    return all(cache.column_exists("destinations", c) for c in cols)


def _apply_004(cache: SchemaCache, engine: Any) -> None:
    ts_type = _timestamp_type(engine)
    cols = [
        ("last_scheduler_check_at", ts_type),
        ("last_cycle_at", ts_type),
        ("last_job_created_at", ts_type),
        ("last_skip_reason", "TEXT"),
    ]
    for col, col_type in cols:
        if cache.table_exists("destinations") and not cache.column_exists("destinations", col):
            with log_step(f"add_col_destinations_{col}"):
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE destinations ADD COLUMN {col} {col_type}"))
                cache.add_column("destinations", col)


# --- Migration 005: Douyin Sources Inventory Columns ---
def _verify_005(cache: SchemaCache, engine: Any) -> bool:
    cols = [
        "original_profile_url",
        "inventory_sync_status",
        "destination_id",
        "inventory_count",
        "inventory_synced_at",
        "inventory_sync_error",
    ]
    return all(cache.column_exists("douyin_sources", c) for c in cols)


def _apply_005(cache: SchemaCache, engine: Any) -> None:
    ts_type = _timestamp_type(engine)
    cols = [
        ("original_profile_url", "TEXT"),
        ("inventory_sync_status", "VARCHAR(20) DEFAULT 'idle'"),
        ("destination_id", "VARCHAR(36)"),
        ("inventory_count", "INTEGER DEFAULT 0"),
        ("inventory_synced_at", ts_type),
        ("inventory_sync_error", "TEXT"),
    ]
    for col, col_type in cols:
        if cache.table_exists("douyin_sources") and not cache.column_exists("douyin_sources", col):
            with log_step(f"add_col_douyin_sources_{col}"):
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE douyin_sources ADD COLUMN {col} {col_type}"))
                cache.add_column("douyin_sources", col)


# --- Migration 006: Douyin Sources Auto Discovery Columns ---
def _verify_006(cache: SchemaCache, engine: Any) -> bool:
    key_cols = [
        "cookie_encrypted",
        "cookie_status",
        "feed_provider",
        "initial_import_status",
        "baseline_done",
    ]
    return all(cache.column_exists("douyin_sources", c) for c in key_cols)


def _apply_006(cache: SchemaCache, engine: Any) -> None:
    ts_type = _timestamp_type(engine)
    json_type = "TEXT" if is_sqlite_dialect(engine) else "JSON"
    cols = [
        ("cookie_encrypted", "TEXT"),
        ("cookie_status", "VARCHAR(20) DEFAULT 'missing'"),
        ("cookie_account_name", "VARCHAR(300)"),
        ("cookie_verified_at", ts_type),
        ("needs_reauth", "BOOLEAN DEFAULT FALSE"),
        ("scan_interval_minutes", "INTEGER DEFAULT 15"),
        ("max_videos_per_day", "INTEGER DEFAULT 50"),
        ("include_keywords", json_type),
        ("exclude_keywords", json_type),
        ("next_scan_at", ts_type),
        ("last_scan_at", ts_type),
        ("start_mode", "VARCHAR(20) DEFAULT 'new_only'"),
        ("initial_limit", "INTEGER DEFAULT 10"),
        ("baseline_done", "BOOLEAN DEFAULT FALSE"),
        ("borderline_policy", "VARCHAR(20) DEFAULT 'hold'"),
        ("mismatch_policy", "VARCHAR(20) DEFAULT 'reject'"),
        ('"order"', "VARCHAR(20) DEFAULT 'oldest_first'"),
        ("feed_provider", "VARCHAR(50) DEFAULT 'rapidapi_justone'"),
        ("initial_import_status", "VARCHAR(20) DEFAULT 'pending'"),
        ("initial_import_cursor", "VARCHAR(64)"),
        ("initial_import_pages", "INTEGER DEFAULT 0"),
        ("initial_import_videos", "INTEGER DEFAULT 0"),
        ("initial_import_last_error", "TEXT"),
        ("initial_import_started_at", ts_type),
        ("initial_import_completed_at", ts_type),
        ("last_refresh_at", ts_type),
        ("provider_status", "VARCHAR(30) DEFAULT 'ok'"),
        ("provider_status_detail", "TEXT"),
    ]
    for col, col_type in cols:
        clean_col = col.strip('"')
        if cache.table_exists("douyin_sources") and not cache.column_exists("douyin_sources", clean_col):
            with log_step(f"add_col_douyin_sources_{clean_col}"):
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE douyin_sources ADD COLUMN {col} {col_type}"))
                cache.add_column("douyin_sources", clean_col)

    # Guarded backfills (BƯỚC 6)
    safe_backfill_update(
        engine,
        "backfill_douyin_sources_initial_import_status",
        "SELECT COUNT(*) FROM douyin_sources WHERE initial_import_status = 'pending' AND (inventory_count > 0 OR last_scan_at IS NOT NULL OR inventory_synced_at IS NOT NULL)",
        "UPDATE douyin_sources SET initial_import_status = 'completed' WHERE initial_import_status = 'pending' AND (inventory_count > 0 OR last_scan_at IS NOT NULL OR inventory_synced_at IS NOT NULL)",
    )
    safe_backfill_update(
        engine,
        "backfill_douyin_sources_baseline_done",
        "SELECT COUNT(*) FROM douyin_sources WHERE baseline_done = FALSE AND (inventory_count > 0 OR last_scan_at IS NOT NULL OR inventory_synced_at IS NOT NULL)",
        "UPDATE douyin_sources SET baseline_done = TRUE WHERE baseline_done = FALSE AND (inventory_count > 0 OR last_scan_at IS NOT NULL OR inventory_synced_at IS NOT NULL)",
    )


# --- Migration 007: Douyin Videos Metadata Columns & Unique Constraint ---
def _verify_007(cache: SchemaCache, engine: Any) -> bool:
    cols = ["match_level", "hold_reason", "is_backfill", "thumbnail_url"]
    cols_exist = all(cache.column_exists("douyin_videos", c) for c in cols)
    idx_exist = cache.index_exists("douyin_videos", "uq_douyin_video_source_video")
    return cols_exist and idx_exist


def _apply_007(cache: SchemaCache, engine: Any) -> None:
    is_sqlite = is_sqlite_dialect(engine)
    cols = [
        ("match_level", "VARCHAR(20)"),
        ("hold_reason", "TEXT"),
        ("is_backfill", "BOOLEAN DEFAULT FALSE"),
        ("thumbnail_url", "TEXT"),
    ]
    for col, col_type in cols:
        if cache.table_exists("douyin_videos") and not cache.column_exists("douyin_videos", col):
            with log_step(f"add_col_douyin_videos_{col}"):
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE douyin_videos ADD COLUMN {col} {col_type}"))
                cache.add_column("douyin_videos", col)

    # Dedupe duplicate (source_id, video_id) if any exist
    with log_step("dedupe_douyin_videos"):
        with engine.connect() as conn:
            dupes = conn.execute(
                text(
                    "SELECT source_id, video_id, COUNT(*) c FROM douyin_videos "
                    "WHERE source_id IS NOT NULL "
                    "GROUP BY source_id, video_id HAVING COUNT(*) > 1"
                )
            ).fetchall()
        if dupes:
            with engine.begin() as conn:
                for row in dupes:
                    conn.execute(
                        text(
                            "DELETE FROM douyin_videos "
                            "WHERE id IN (SELECT id FROM douyin_videos WHERE source_id = :sid AND video_id = :vid ORDER BY id DESC LIMIT -1 OFFSET 1)"
                        ),
                        {"sid": row[0], "vid": row[1]},
                    )

    # Unique constraint / index
    if not cache.index_exists("douyin_videos", "uq_douyin_video_source_video"):
        with log_step("create_index_uq_douyin_video_source_video"):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_douyin_video_source_video "
                        "ON douyin_videos (source_id, video_id)"
                    )
                )
            cache.add_index("douyin_videos", "uq_douyin_video_source_video")

    # PostgreSQL only: ALTER COLUMN source_id DROP NOT NULL
    if not is_sqlite:
        with log_step("pg_drop_not_null_douyin_videos_source_id"):
            try:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE douyin_videos ALTER COLUMN source_id DROP NOT NULL"))
            except Exception:
                pass


# --- Migration 008: AI Comment Reply Columns & Table ---
def _verify_008(cache: SchemaCache, engine: Any) -> bool:
    tbl_ok = cache.table_exists("youtube_comments")
    dest_col_ok = cache.column_exists("destinations", "comment_reply_enabled")
    return tbl_ok and dest_col_ok


def _apply_008(cache: SchemaCache, engine: Any) -> None:
    ts_type = _timestamp_type(engine)
    if not cache.table_exists("destinations"):
        return

    cols = [
        ("min_upload_interval_minutes", "INTEGER DEFAULT 0"),
        ("comment_reply_enabled", "BOOLEAN DEFAULT FALSE"),
        ("comment_reply_mode", "VARCHAR(20) DEFAULT 'off'"),
        ("comment_reply_system_prompt", "TEXT"),
        ("comment_reply_language", "VARCHAR(20) DEFAULT 'auto'"),
        ("comment_reply_style", "VARCHAR(30) DEFAULT 'friendly'"),
        ("comment_reply_daily_limit", "INTEGER DEFAULT 20"),
        ("comment_reply_min_interval_seconds", "INTEGER DEFAULT 180"),
        ("comment_reply_new_only", "BOOLEAN DEFAULT TRUE"),
        ("comment_reply_to_positive", "BOOLEAN DEFAULT TRUE"),
        ("comment_reply_to_questions", "BOOLEAN DEFAULT TRUE"),
        ("comment_reply_to_neutral", "BOOLEAN DEFAULT FALSE"),
        ("comment_reply_to_negative", "BOOLEAN DEFAULT FALSE"),
        ("comment_reply_to_emoji_only", "BOOLEAN DEFAULT FALSE"),
        ("comment_reply_to_funny", "BOOLEAN DEFAULT FALSE"),
        ("comment_reply_to_excited", "BOOLEAN DEFAULT FALSE"),
        ("last_comment_scan_at", ts_type),
    ]
    for col, col_type in cols:
        if not cache.column_exists("destinations", col):
            with log_step(f"add_col_destinations_{col}"):
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE destinations ADD COLUMN {col} {col_type}"))
                cache.add_column("destinations", col)

    if not cache.table_exists("youtube_comments"):
        with log_step("create_table_youtube_comments"):
            with engine.begin() as conn:
                Base.metadata.create_all(bind=conn, tables=[YouTubeComment.__table__])
            cache.add_table("youtube_comments", [c.name for c in YouTubeComment.__table__.columns])


# --- Migration 009: Pipeline Scheduler Columns ---
def _verify_009(cache: SchemaCache, engine: Any) -> bool:
    cols = [
        "daily_upload_limit",
        "upload_slots",
        "backlog_slots_per_day",
        "new_slots_per_day",
        "backlog_order",
        "source_selection_strategy",
        "source_selection_cursor",
        "backlog_threshold_days",
        "timezone",
    ]
    return all(cache.column_exists("pipelines", c) for c in cols)


def _apply_009(cache: SchemaCache, engine: Any) -> None:
    json_type = "TEXT" if is_sqlite_dialect(engine) else "JSON"
    pipeline_columns = [
        ("daily_upload_limit", "INTEGER DEFAULT 6"),
        ("upload_slots", json_type),
        ("backlog_slots_per_day", "INTEGER DEFAULT 4"),
        ("new_slots_per_day", "INTEGER DEFAULT 2"),
        ("backlog_order", "VARCHAR(10) DEFAULT 'asc'"),
        ("source_selection_strategy", "VARCHAR(50) DEFAULT 'round_robin'"),
        ("source_selection_cursor", "INTEGER DEFAULT 0"),
        ("backlog_threshold_days", "INTEGER DEFAULT 7"),
        ("timezone", "VARCHAR(50) DEFAULT 'UTC'"),
    ]
    for col, col_type in pipeline_columns:
        if cache.table_exists("pipelines") and not cache.column_exists("pipelines", col):
            with log_step(f"add_col_pipelines_{col}"):
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE pipelines ADD COLUMN {col} {col_type}"))
                cache.add_column("pipelines", col)


# --- Migration 010: YouTube Scheduled Publishing Columns ---
def _verify_010(cache: SchemaCache, engine: Any) -> bool:
    checks = [
        ("destinations", "youtube_default_publish_mode"),
        ("publications", "publication_mode"),
        ("publications", "youtube_publish_mode"),
        ("video_jobs", "youtube_publish_mode"),
        ("pipelines", "youtube_default_publish_mode"),
    ]
    return all(cache.column_exists(tbl, col) for tbl, col in checks)


def _apply_010(cache: SchemaCache, engine: Any) -> None:
    ts_type = _timestamp_type(engine)
    if cache.table_exists("destinations") and not cache.column_exists("destinations", "youtube_default_publish_mode"):
        with log_step("add_col_destinations_youtube_default_publish_mode"):
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE destinations ADD COLUMN youtube_default_publish_mode VARCHAR(20) DEFAULT 'immediate'"))
            cache.add_column("destinations", "youtube_default_publish_mode")

    if cache.table_exists("publications") and not cache.column_exists("publications", "publication_mode"):
        with log_step("add_col_publications_publication_mode"):
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE publications ADD COLUMN publication_mode VARCHAR(20) DEFAULT 'auto'"))
            cache.add_column("publications", "publication_mode")

    pub_cols = [
        ("youtube_publish_mode", "VARCHAR(20) DEFAULT 'immediate'"),
        ("youtube_publish_at", ts_type),
        ("youtube_schedule_timezone", "VARCHAR(50) DEFAULT 'Asia/Ho_Chi_Minh'"),
        ("youtube_scheduled", "BOOLEAN DEFAULT FALSE"),
        ("youtube_actual_published_at", ts_type),
        ("youtube_privacy_status", "VARCHAR(20)"),
    ]
    for col, col_type in pub_cols:
        if cache.table_exists("publications") and not cache.column_exists("publications", col):
            with log_step(f"add_col_publications_{col}"):
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE publications ADD COLUMN {col} {col_type}"))
                cache.add_column("publications", col)

    job_cols = [
        ("youtube_publish_mode", "VARCHAR(20) DEFAULT 'immediate'"),
        ("youtube_publish_at", ts_type),
        ("youtube_schedule_timezone", "VARCHAR(50) DEFAULT 'Asia/Ho_Chi_Minh'"),
        ("youtube_scheduled", "BOOLEAN DEFAULT FALSE"),
        ("youtube_actual_published_at", ts_type),
    ]
    for col, col_type in job_cols:
        if cache.table_exists("video_jobs") and not cache.column_exists("video_jobs", col):
            with log_step(f"add_col_video_jobs_{col}"):
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE video_jobs ADD COLUMN {col} {col_type}"))
                cache.add_column("video_jobs", col)

    if cache.table_exists("pipelines") and not cache.column_exists("pipelines", "youtube_default_publish_mode"):
        with log_step("add_col_pipelines_youtube_default_publish_mode"):
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE pipelines ADD COLUMN youtube_default_publish_mode VARCHAR(20) DEFAULT 'immediate'"))
            cache.add_column("pipelines", "youtube_default_publish_mode")

    # Guarded backfill (BƯỚC 6)
    safe_backfill_update(
        engine,
        "backfill_publications_youtube_publish_mode",
        "SELECT COUNT(*) FROM publications WHERE youtube_publish_mode IS NULL",
        "UPDATE publications SET youtube_publish_mode='immediate' WHERE youtube_publish_mode IS NULL",
    )
    safe_backfill_update(
        engine,
        "backfill_video_jobs_youtube_publish_mode",
        "SELECT COUNT(*) FROM video_jobs WHERE youtube_publish_mode IS NULL",
        "UPDATE video_jobs SET youtube_publish_mode='immediate' WHERE youtube_publish_mode IS NULL",
    )
    safe_backfill_update(
        engine,
        "backfill_destinations_youtube_default_publish_mode",
        "SELECT COUNT(*) FROM destinations WHERE youtube_default_publish_mode IS NULL",
        "UPDATE destinations SET youtube_default_publish_mode='immediate' WHERE youtube_default_publish_mode IS NULL",
    )


# --- Migration 011: Indexes ---
def _verify_011(cache: SchemaCache, engine: Any) -> bool:
    indexes = [
        ("video_jobs", "ix_video_jobs_pipeline_id"),
        ("publications", "ix_publications_pipeline_id"),
        ("douyin_videos", "ix_douyin_videos_pipeline_id"),
        ("douyin_sources", "ix_douyin_sources_pipeline_id"),
        ("destinations", "ix_destinations_pipeline_id"),
        ("publications", "uq_publication_destination_scheduled_at"),
    ]
    return all(cache.index_exists(tbl, idx) for tbl, idx in indexes)


def _apply_011(cache: SchemaCache, engine: Any) -> None:
    indexes = [
        ("ix_video_jobs_pipeline_id", "video_jobs", "pipeline_id"),
        ("ix_publications_pipeline_id", "publications", "pipeline_id"),
        ("ix_douyin_videos_pipeline_id", "douyin_videos", "pipeline_id"),
        ("ix_douyin_sources_pipeline_id", "douyin_sources", "pipeline_id"),
        ("ix_destinations_pipeline_id", "destinations", "pipeline_id"),
    ]
    for idx, tbl, col in indexes:
        if cache.table_exists(tbl) and not cache.index_exists(tbl, idx):
            with log_step(f"create_index_{idx}"):
                with engine.begin() as conn:
                    conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx} ON {tbl} ({col})"))
                cache.add_index(tbl, idx)

    if cache.table_exists("publications") and not cache.index_exists("publications", "uq_publication_destination_scheduled_at"):
        with log_step("create_index_uq_publication_destination_scheduled_at"):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_publication_destination_scheduled_at "
                        "ON publications (destination_id, scheduled_at)"
                    )
                )
            cache.add_index("publications", "uq_publication_destination_scheduled_at")


# --- Migration 012: Default Pipeline ---
def _verify_012(cache: SchemaCache, engine: Any) -> bool:
    if not cache.table_exists("pipelines"):
        return False
    with engine.connect() as conn:
        res = conn.execute(
            text("SELECT 1 FROM pipelines WHERE slug = :slug LIMIT 1"),
            {"slug": DEFAULT_PIPELINE_SLUG},
        ).fetchone()
        return res is not None


def _apply_012(cache: SchemaCache, engine: Any) -> None:
    with log_step("ensure_default_pipeline"):
        ensure_default_pipeline(engine)


# --- Migration 013: Tenant Multi-User & Workspace Backfill ---
def _verify_013(cache: SchemaCache, engine: Any) -> bool:
    auth_tables = {"workspaces", "users", "workspace_members", "user_sessions"}
    if not auth_tables.issubset(cache.tables):
        return False
    for tbl in ["pipelines", "destinations", "video_jobs", "publications"]:
        if not cache.column_exists(tbl, "workspace_id"):
            return False
    # Check if there are NULL workspace_id rows in pipelines
    with engine.connect() as conn:
        null_count = conn.execute(
            text("SELECT COUNT(*) FROM pipelines WHERE workspace_id IS NULL")
        ).fetchone()[0]
        return null_count == 0


def _apply_013(cache: SchemaCache, engine: Any) -> None:
    # 1. Auth tables
    for model_cls in (User, Workspace, WorkspaceMember, UserSession):
        tbl_name = model_cls.__table__.name
        if not cache.table_exists(tbl_name):
            with log_step(f"create_table_{tbl_name}"):
                with engine.begin() as conn:
                    Base.metadata.create_all(bind=conn, tables=[model_cls.__table__])
                cache.add_table(tbl_name, [c.name for c in model_cls.__table__.columns])

    # 2. workspace_id column on tenant tables
    for tbl in _TENANT_TABLES:
        if cache.table_exists(tbl) and not cache.column_exists(tbl, "workspace_id"):
            with log_step(f"add_col_{tbl}_workspace_id"):
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN workspace_id VARCHAR(36)"))
                    conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{tbl}_workspace_id ON {tbl} (workspace_id)"))
                cache.add_column(tbl, "workspace_id")
                cache.add_index(tbl, f"ix_{tbl}_workspace_id")

    if cache.table_exists("oauth_states") and not cache.column_exists("oauth_states", "initiated_by_user_id"):
        with log_step("add_col_oauth_states_initiated_by_user_id"):
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE oauth_states ADD COLUMN initiated_by_user_id VARCHAR(36)"))
            cache.add_column("oauth_states", "initiated_by_user_id")

    # 3. Composite tenant indexes
    comp_indexes = [
        ("ix_douyin_videos_workspace_created", "douyin_videos", "(workspace_id, created_at)"),
        ("ix_douyin_videos_workspace_pipeline", "douyin_videos", "(workspace_id, pipeline_id)"),
        ("ix_youtube_comments_workspace_dest", "youtube_comments", "(workspace_id, destination_id)"),
        ("ix_publications_workspace_dest", "publications", "(workspace_id, destination_id)"),
        ("ix_publications_workspace_created", "publications", "(workspace_id, created_at)"),
        ("ix_publications_workspace_pipeline", "publications", "(workspace_id, pipeline_id)"),
        ("ix_video_jobs_workspace_pipeline", "video_jobs", "(workspace_id, pipeline_id)"),
        ("ix_video_jobs_workspace_dest", "video_jobs", "(workspace_id, destination_id)"),
        ("ix_destinations_workspace_pipeline", "destinations", "(workspace_id, pipeline_id)"),
        ("ix_douyin_sources_workspace_pipeline", "douyin_sources", "(workspace_id, pipeline_id)"),
    ]
    for idx, tbl, cols in comp_indexes:
        if cache.table_exists(tbl) and not cache.index_exists(tbl, idx):
            with log_step(f"create_index_{idx}"):
                with engine.begin() as conn:
                    conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx} ON {tbl} {cols}"))
                cache.add_index(tbl, idx)

    # 4. Admin workspace
    import uuid as _uuid
    now_fn = _now_expr(engine)
    with engine.connect() as conn:
        admin_ws = conn.execute(
            text("SELECT id FROM workspaces WHERE name = :name LIMIT 1"),
            {"name": ADMIN_WORKSPACE_NAME},
        ).fetchone()

    if admin_ws is None:
        admin_ws_id = str(_uuid.uuid4())
        with log_step("create_admin_workspace"):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO workspaces (id, name, owner_user_id, created_at, updated_at) "
                        f"VALUES (:id, :name, NULL, {now_fn}, {now_fn})"
                    ),
                    {"id": admin_ws_id, "name": ADMIN_WORKSPACE_NAME},
                )
    else:
        admin_ws_id = admin_ws[0]

    # 5. Guarded backfills (BƯỚC 6)
    safe_backfill_update(
        engine,
        "backfill_pipelines_workspace_id",
        "SELECT COUNT(*) FROM pipelines WHERE workspace_id IS NULL",
        "UPDATE pipelines SET workspace_id = :ws WHERE workspace_id IS NULL",
        {"ws": admin_ws_id},
    )

    for tbl in ("destinations", "pipeline_sources", "douyin_sources", "douyin_videos", "publications", "video_jobs"):
        if not cache.table_exists(tbl):
            continue
        safe_backfill_update(
            engine,
            f"backfill_{tbl}_workspace_from_pipeline",
            f"SELECT COUNT(*) FROM {tbl} WHERE workspace_id IS NULL AND pipeline_id IS NOT NULL",
            f"UPDATE {tbl} SET workspace_id = (SELECT workspace_id FROM pipelines WHERE pipelines.id = {tbl}.pipeline_id) WHERE {tbl}.workspace_id IS NULL AND {tbl}.pipeline_id IS NOT NULL",
        )
        safe_backfill_update(
            engine,
            f"backfill_{tbl}_workspace_orphan_admin",
            f"SELECT COUNT(*) FROM {tbl} WHERE workspace_id IS NULL",
            f"UPDATE {tbl} SET workspace_id = :ws WHERE workspace_id IS NULL",
            {"ws": admin_ws_id},
        )

    for tbl in (
        "youtube_comments",
        "youtube_channel_analytics_daily",
        "youtube_video_analytics_daily",
        "youtube_research_runs",
        "youtube_research_items",
        "youtube_channel_dna",
        "youtube_content_fingerprints",
        "youtube_performance_snapshots",
        "youtube_dna_suggestions",
        "youtube_daily_publish_overrides",
    ):
        if not cache.table_exists(tbl):
            continue
        safe_backfill_update(
            engine,
            f"backfill_{tbl}_workspace_from_dest",
            f"SELECT COUNT(*) FROM {tbl} WHERE workspace_id IS NULL AND destination_id IS NOT NULL",
            f"UPDATE {tbl} SET workspace_id = (SELECT workspace_id FROM destinations WHERE destinations.id = {tbl}.destination_id) WHERE {tbl}.workspace_id IS NULL AND {tbl}.destination_id IS NOT NULL",
        )
        safe_backfill_update(
            engine,
            f"backfill_{tbl}_workspace_orphan_admin",
            f"SELECT COUNT(*) FROM {tbl} WHERE workspace_id IS NULL",
            f"UPDATE {tbl} SET workspace_id = :ws WHERE workspace_id IS NULL",
            {"ws": admin_ws_id},
        )

    # 6. Bootstrap system admin user if credentials provided
    admin_email = (getattr(settings, "admin_email", "") or "").strip().lower()
    admin_pw = getattr(settings, "admin_initial_password", "") or ""
    if admin_email and admin_pw:
        with log_step("bootstrap_system_admin_user"):
            with engine.connect() as conn:
                exists = conn.execute(
                    text("SELECT 1 FROM users WHERE email = :email LIMIT 1"),
                    {"email": admin_email},
                ).fetchone()
            if exists is None:
                from app.auth import hash_password as _hash_pw
                uid = str(_uuid.uuid4())
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            "INSERT INTO users (id, email, password_hash, display_name, status, is_system_admin, created_at, updated_at) "
                            f"VALUES (:id, :email, :pw, 'System Admin', 'active', TRUE, {now_fn}, {now_fn})"
                        ),
                        {"id": uid, "email": admin_email, "pw": _hash_pw(admin_pw)},
                    )
                    conn.execute(
                        text(
                            "INSERT INTO workspace_members (id, workspace_id, user_id, role, created_at) "
                            f"VALUES (:id, :ws, :uid, 'owner', {now_fn})"
                        ),
                        {"id": str(_uuid.uuid4()), "ws": admin_ws_id, "uid": uid},
                    )


# --- Migration 014: Legacy Destination Sync ---
def _verify_014(cache: SchemaCache, engine: Any) -> bool:
    if not cache.table_exists("video_jobs"):
        return True
    with engine.connect() as conn:
        unassigned = conn.execute(
            text("SELECT COUNT(*) FROM video_jobs WHERE pipeline_id IS NULL")
        ).fetchone()[0]
        return unassigned == 0


def _apply_014(cache: SchemaCache, engine: Any) -> None:
    with log_step("destination_and_job_sync"):
        with engine.connect() as conn:
            pipe_row = conn.execute(
                text("SELECT id FROM pipelines WHERE slug = :slug LIMIT 1"),
                {"slug": DEFAULT_PIPELINE_SLUG},
            ).fetchone()
        if pipe_row is not None:
            default_pipeline_id = pipe_row[0]
            migrate_existing_youtube_to_destination(engine)
            assign_existing_jobs_to_default(engine, default_pipeline_id)


def _verify_015(cache: SchemaCache, engine: Any) -> bool:
    has_pub_dest = "ix_publications_destination_id" in cache.indexes.get("publications", [])
    has_job_pub = "ix_video_jobs_publication_id" in cache.indexes.get("video_jobs", [])
    return has_pub_dest and has_job_pub

def _apply_015(cache: SchemaCache, engine: Any) -> None:
    queries = [
        "CREATE INDEX IF NOT EXISTS ix_publications_destination_id ON publications(destination_id)",
        "CREATE INDEX IF NOT EXISTS ix_publications_status_created ON publications(status, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_publications_status_published ON publications(status, published_at)",
        "CREATE INDEX IF NOT EXISTS ix_video_jobs_publication_id ON video_jobs(publication_id)"
    ]
    with engine.begin() as conn:
        for q in queries:
            try:
                conn.execute(text(q))
            except Exception as e:
                pass


# Registry of all migrations in chronological order
MIGRATIONS = [
    MigrationDefinition("20240101_001_core_tables", "Core base tables", _verify_001, _apply_001),
    MigrationDefinition("20240102_002_analytics_tables", "Analytics & research tables", _verify_002, _apply_002),
    MigrationDefinition("20240103_003_core_columns", "Core column additions", _verify_003, _apply_003),
    MigrationDefinition("20240104_004_destinations_scheduler", "Destinations scheduler columns", _verify_004, _apply_004),
    MigrationDefinition("20240105_005_douyin_sources_inventory", "Douyin sources inventory columns", _verify_005, _apply_005),
    MigrationDefinition("20240106_006_douyin_sources_auto_discovery", "Douyin sources auto mode & discovery columns", _verify_006, _apply_006),
    MigrationDefinition("20240107_007_douyin_videos_metadata", "Douyin videos match & hold columns", _verify_007, _apply_007),
    MigrationDefinition("20240108_008_ai_comment_reply", "AI comment reply columns & youtube_comments table", _verify_008, _apply_008),
    MigrationDefinition("20240109_009_pipeline_scheduler", "Pipeline upload slots & scheduler columns", _verify_009, _apply_009),
    MigrationDefinition("20240110_010_youtube_scheduled_publishing", "YouTube scheduled publishing columns", _verify_010, _apply_010),
    MigrationDefinition("20240111_011_indexes", "Core performance & slot indexes", _verify_011, _apply_011),
    MigrationDefinition("20240112_012_default_pipeline", "Default pipeline seed", _verify_012, _apply_012),
    MigrationDefinition("20240113_013_tenant_multiuser", "Multi-tenant auth & workspace backfill", _verify_013, _apply_013),
    MigrationDefinition("20240114_014_destination_sync", "Legacy YouTube OAuth migration & job assignment", _verify_014, _apply_014),
    MigrationDefinition("20240115_015_performance_indexes", "Channel workspace performance indexes", _verify_015, _apply_015),
]


# =====================================================================
# PUBLIC MIGRATION RUNNER
# =====================================================================

def run_migrations(engine_override: Any = None) -> None:
    """Executes or baselines all migrations.
    Uses short, isolated transactions (no giant transaction).
    Uses in-memory SchemaCache to eliminate redundant remote queries.
    Strictly separates PostgreSQL and Turso / SQLite dialects.
    """
    global _active_cache
    engine = engine_override or default_engine
    is_sqlite = is_sqlite_dialect(engine)

    t_start = time.perf_counter()
    logger.info("Starting run_migrations (dialect=%s)", engine.dialect.name)

    # 1. Ensure schema_migrations table exists
    ensure_schema_migrations_table(engine)

    # 2. Get applied versions
    applied_versions = get_applied_migrations(engine)

    # 3. Check if all migrations are already recorded
    all_versions = [m.version for m in MIGRATIONS]
    if all(v in applied_versions for v in all_versions):
        elapsed_ms = (time.perf_counter() - t_start) * 1000.0
        print(f"[MIGRATION OK] all_migrations_up_to_date {elapsed_ms:.2f}ms (0 pending)", flush=True)
        logger.info("[MIGRATION OK] all_migrations_up_to_date %.2fms (0 pending)", elapsed_ms)
        return

    # 4. Load schema once into in-memory cache
    with log_step("load_schema_cache"):
        with engine.connect() as conn:
            cache = SchemaCache(conn, is_sqlite)
    _active_cache = cache

    try:
        # 5. Process each migration
        for m in MIGRATIONS:
            if m.version in applied_versions:
                continue

            # Verify if schema for this migration already corresponds after Supabase import
            with log_step(f"verify_{m.version}"):
                already_satisfied = m.verify_fn(cache, engine)

            if already_satisfied:
                with log_step(f"baseline_{m.version}"):
                    record_migration(engine, m.version)
                    applied_versions.add(m.version)
            else:
                with log_step(f"apply_{m.version}"):
                    m.apply_fn(cache, engine)
                    record_migration(engine, m.version)
                    applied_versions.add(m.version)

        total_duration_ms = (time.perf_counter() - t_start) * 1000.0
        print(f"[MIGRATION OK] run_migrations_complete {total_duration_ms:.2f}ms", flush=True)
        logger.info("[MIGRATION OK] run_migrations_complete %.2fms", total_duration_ms)

    finally:
        _active_cache = None


# =====================================================================
# INDIVIDUAL HELPERS FOR DIRECT CALLERS / TESTS
# =====================================================================

def ensure_default_pipeline(connection_or_engine: Any) -> str | None:
    # Accept both Connection and Engine
    engine = connection_or_engine if hasattr(connection_or_engine, "connect") else connection_or_engine
    with Session(bind=engine) as db:
        pipeline = db.execute(
            text("SELECT id FROM pipelines WHERE slug = :slug LIMIT 1"),
            {"slug": DEFAULT_PIPELINE_SLUG},
        ).fetchone()

        if pipeline:
            return pipeline[0]

        pipeline = Pipeline(
            name=DEFAULT_PIPELINE_NAME,
            slug=DEFAULT_PIPELINE_SLUG,
            niche=DEFAULT_PIPELINE_NICHE,
            language=DEFAULT_PIPELINE_LANGUAGE,
            fixed_hashtags=DEFAULT_PIPELINE_FIXED_HASHTAGS,
            adaptive_hashtags=DEFAULT_PIPELINE_ADAPTIVE_HASHTAGS,
            prompt_profile="",
            default_privacy=DEFAULT_PIPELINE_DEFAULT_PRIVACY,
            enabled=True,
        )
        db.add(pipeline)
        db.flush()
        pipeline_id = pipeline.id
        db.commit()
        logger.info("Created default pipeline id=%s name=%s", pipeline_id, DEFAULT_PIPELINE_NAME)
        return pipeline_id


def assign_existing_jobs_to_default(connection_or_engine: Any, default_pipeline_id: str) -> None:
    engine = connection_or_engine if hasattr(connection_or_engine, "connect") else connection_or_engine
    with Session(bind=engine) as db:
        result = db.execute(
            text("UPDATE video_jobs SET pipeline_id = :pipeline_id WHERE pipeline_id IS NULL"),
            {"pipeline_id": default_pipeline_id},
        )
        db.commit()
        logger.info("Assigned %s existing jobs to default pipeline", result.rowcount)


def migrate_existing_youtube_to_destination(connection_or_engine: Any) -> None:
    engine = connection_or_engine if hasattr(connection_or_engine, "connect") else connection_or_engine
    with Session(bind=engine) as db:
        pipelines = db.execute(
            text(
                "SELECT id, youtube_channel_title, youtube_credentials, youtube_channel_id "
                "FROM pipelines "
                "WHERE youtube_credentials IS NOT NULL AND youtube_channel_id IS NOT NULL"
            ),
        ).fetchall()

        for row in pipelines:
            pipeline_id, channel_title, credentials, channel_id = row[0], row[1], row[2], row[3]
            existing = db.execute(
                text("SELECT id FROM destinations WHERE pipeline_id = :pipeline_id AND platform = 'youtube' LIMIT 1"),
                {"pipeline_id": pipeline_id},
            ).fetchone()

            if existing:
                continue

            destination = Destination(
                pipeline_id=pipeline_id,
                platform="youtube",
                name=channel_title or "YouTube",
                external_account_id=channel_id,
                external_account_name=channel_title,
                credentials=credentials,
                connected=True,
                enabled=True,
            )
            db.add(destination)
            try:
                pipe_ws = db.execute(
                    text("SELECT workspace_id FROM pipelines WHERE id = :pid"),
                    {"pid": pipeline_id},
                ).fetchone()
                if pipe_ws is not None and pipe_ws[0]:
                    destination.workspace_id = pipe_ws[0]
            except Exception:
                pass
            db.commit()
            logger.info("Migrated YouTube OAuth for pipeline %s to destination %s", pipeline_id, destination.id)


def run_tenant_migration(connection_or_engine: Any) -> None:
    # Retained for direct callers / test scripts
    engine = connection_or_engine if hasattr(connection_or_engine, "connect") else connection_or_engine
    is_sqlite = is_sqlite_dialect(engine)
    with engine.connect() as conn:
        cache = SchemaCache(conn, is_sqlite)
    _apply_013(cache, engine)
