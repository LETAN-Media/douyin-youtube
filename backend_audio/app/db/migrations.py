"""Versioned, idempotent migrations for backend_audio."""

from __future__ import annotations

import logging

from app.db.client import SCHEMA_VERSION_TABLE, get_client

logger = logging.getLogger("backend-audio.migrations")

MIGRATIONS: list[tuple[str, list[str]]] = [
    (
        "audio_001",
        [
            f"""CREATE TABLE IF NOT EXISTS {SCHEMA_VERSION_TABLE} (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )""",
            """CREATE TABLE IF NOT EXISTS audio_pipelines (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                auto_publish INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )""",
            """CREATE TABLE IF NOT EXISTS audio_sources (
                id TEXT PRIMARY KEY,
                pipeline_id TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'facebook_page',
                url TEXT NOT NULL,
                canonical_url TEXT,
                page_id TEXT,
                page_name TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_scanned_at TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                UNIQUE(pipeline_id, canonical_url)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_audio_sources_pipeline ON audio_sources(pipeline_id, enabled)",
            """CREATE TABLE IF NOT EXISTS audio_inventory (
                id TEXT PRIMARY KEY,
                pipeline_id TEXT NOT NULL,
                source_id TEXT,
                facebook_video_id TEXT,
                canonical_url TEXT NOT NULL,
                thumbnail_url TEXT,
                duration_seconds REAL,
                caption TEXT,
                status TEXT NOT NULL DEFAULT 'available',
                discovered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                UNIQUE(pipeline_id, facebook_video_id)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_audio_inventory_queue ON audio_inventory(pipeline_id, status, discovered_at)",
            "CREATE INDEX IF NOT EXISTS idx_audio_inventory_source ON audio_inventory(source_id, status)",
        ],
    ),
    (
        "audio_002",
        [
            """CREATE TABLE IF NOT EXISTS audio_destinations (
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
            )""",
            "CREATE INDEX IF NOT EXISTS idx_audio_dest_pipeline ON audio_destinations(pipeline_id, connected)",
            """CREATE TABLE IF NOT EXISTS audio_youtube_credentials (
                destination_id TEXT PRIMARY KEY,
                channel_id TEXT,
                refresh_token_encrypted TEXT,
                token_uri TEXT NOT NULL DEFAULT 'https://oauth2.googleapis.com/token',
                status TEXT NOT NULL DEFAULT 'active',
                connected_at TEXT,
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )""",
            """CREATE TABLE IF NOT EXISTS audio_oauth_states (
                state TEXT PRIMARY KEY,
                destination_id TEXT NOT NULL,
                pipeline_id TEXT NOT NULL,
                return_to TEXT,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )""",
        ],
    ),
    (
        "audio_003",
        [
            """CREATE TABLE IF NOT EXISTS audio_media_assets (
                id TEXT PRIMARY KEY,
                pipeline_id TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'background',
                object_key TEXT NOT NULL,
                file_name TEXT,
                mime TEXT,
                width INTEGER,
                height INTEGER,
                duration_seconds REAL,
                bytes INTEGER,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                UNIQUE(pipeline_id, object_key)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_audio_media_pipeline ON audio_media_assets(pipeline_id, kind, enabled)",
            """CREATE TABLE IF NOT EXISTS audio_processing_jobs (
                id TEXT PRIMARY KEY,
                pipeline_id TEXT NOT NULL,
                inventory_id TEXT,
                manual_url TEXT,
                mode TEXT NOT NULL DEFAULT 'auto',
                status TEXT NOT NULL DEFAULT 'queued',
                stage TEXT NOT NULL DEFAULT 'queued',
                progress_percent INTEGER NOT NULL DEFAULT 0,
                background_asset_id TEXT,
                logo_asset_id TEXT,
                srt_object_key TEXT,
                ai_title TEXT,
                ai_description TEXT,
                ai_hashtags_json TEXT,
                ai_metadata_status TEXT,
                youtube_video_id TEXT,
                youtube_url TEXT,
                last_error_code TEXT,
                last_error_message TEXT,
                run_at TEXT,
                lease_owner TEXT,
                lease_expires_at TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )""",
            "CREATE INDEX IF NOT EXISTS idx_audio_jobs_pipeline ON audio_processing_jobs(pipeline_id, status, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_audio_jobs_inventory ON audio_processing_jobs(inventory_id, status)",
            """CREATE TABLE IF NOT EXISTS audio_job_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                state TEXT NOT NULL,
                detail TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )""",
            "CREATE INDEX IF NOT EXISTS idx_audio_job_events_job ON audio_job_events(job_id, created_at)",
        ],
    ),
    (
        "audio_004",
        [
            """CREATE TABLE IF NOT EXISTS audio_publications (
                id TEXT PRIMARY KEY,
                pipeline_id TEXT NOT NULL,
                inventory_id TEXT,
                job_id TEXT,
                destination_id TEXT NOT NULL,
                facebook_video_id TEXT,
                canonical_url TEXT,
                youtube_video_id TEXT,
                youtube_url TEXT,
                title TEXT,
                status TEXT NOT NULL DEFAULT 'published',
                published_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                UNIQUE(pipeline_id, destination_id, facebook_video_id)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_audio_pub_lookup ON audio_publications(pipeline_id, destination_id, status)",
            """CREATE TABLE IF NOT EXISTS audio_ai_settings (
                pipeline_id TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                language TEXT NOT NULL DEFAULT 'vi',
                genre TEXT,
                generate_title INTEGER NOT NULL DEFAULT 1,
                generate_description INTEGER NOT NULL DEFAULT 1,
                generate_hashtags INTEGER NOT NULL DEFAULT 1,
                system_prompt TEXT,
                title_template TEXT,
                description_template TEXT,
                locked_hashtags_json TEXT NOT NULL DEFAULT '[]',
                model_override TEXT,
                config_version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )""",
            """CREATE TABLE IF NOT EXISTS audio_scheduler_settings (
                pipeline_id TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                destination_id TEXT,
                max_videos_per_day INTEGER NOT NULL DEFAULT 3,
                min_gap_minutes INTEGER NOT NULL DEFAULT 120,
                timezone TEXT NOT NULL DEFAULT 'Asia/Ho_Chi_Minh',
                daily_times_json TEXT NOT NULL DEFAULT '[]',
                order_mode TEXT NOT NULL DEFAULT 'oldest_first',
                rotate_sources INTEGER NOT NULL DEFAULT 1,
                next_run_at TEXT,
                last_run_at TEXT,
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )""",
        ],
    ),
    (
        "audio_005",
        [
            """CREATE TABLE IF NOT EXISTS audio_processing_settings (
                pipeline_id TEXT PRIMARY KEY,
                subtitle_mode TEXT NOT NULL DEFAULT 'youtube_captions',
                srt_auto_generate INTEGER NOT NULL DEFAULT 1,
                srt_required INTEGER NOT NULL DEFAULT 1,
                srt_object_key TEXT,
                orientation TEXT NOT NULL DEFAULT 'landscape',
                logo_position TEXT NOT NULL DEFAULT 'top-right',
                normalize_audio INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )""",
        ],
    ),
    (
        "audio_006",
        [
            "ALTER TABLE audio_processing_settings ADD COLUMN template_enabled INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE audio_processing_settings ADD COLUMN template_asset_id TEXT",
            "ALTER TABLE audio_processing_settings ADD COLUMN template_interval_s REAL NOT NULL DEFAULT 600",
            "ALTER TABLE audio_processing_jobs ADD COLUMN template_asset_id TEXT",
        ],
    ),
    (
        "audio_007",
        [
            """CREATE TABLE IF NOT EXISTS audio_scan_runs (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                pipeline_id TEXT NOT NULL,
                scan_mode TEXT NOT NULL DEFAULT 'initial',
                status TEXT NOT NULL DEFAULT 'queued',
                next_cursor TEXT,
                pages_fetched INTEGER NOT NULL DEFAULT 0,
                videos_discovered INTEGER NOT NULL DEFAULT 0,
                videos_added INTEGER NOT NULL DEFAULT 0,
                videos_existing INTEGER NOT NULL DEFAULT 0,
                provider_reported_total INTEGER,
                pagination_exhausted INTEGER NOT NULL DEFAULT 0,
                stop_reason TEXT,
                last_error_code TEXT,
                last_error_message TEXT,
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )""",
            "CREATE INDEX IF NOT EXISTS idx_audio_scan_source ON audio_scan_runs(source_id, status, created_at)",
        ],
    ),
    (
        "audio_008",
        [
            "ALTER TABLE audio_pipelines ADD COLUMN pipeline_type TEXT NOT NULL DEFAULT 'auto'",
        ],
    ),
    (
        "audio_009",
        [
            "ALTER TABLE audio_processing_settings ADD COLUMN background_source TEXT NOT NULL DEFAULT 'background'",
        ],
    ),
]


def migrate() -> list[str]:
    client = get_client()
    client.execute(
        f"""CREATE TABLE IF NOT EXISTS {SCHEMA_VERSION_TABLE} (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )"""
    )
    client.commit()
    have = {
        r["version"]
        for r in client.execute(f"SELECT version FROM {SCHEMA_VERSION_TABLE}").fetchall()
    }
    applied: list[str] = []
    for version, statements in MIGRATIONS:
        if version in have:
            continue
        for sql in statements:
            try:
                client.execute(sql)
            except Exception as exc:
                err_str = str(exc).lower()
                if "duplicate column" in err_str or "already exists" in err_str:
                    logger.warning("migration %s statement skipped (already exists): %s", version, exc)
                else:
                    raise
        client.commit()
        client.execute(
            f"INSERT INTO {SCHEMA_VERSION_TABLE} (version) VALUES (?)", (version,)
        )
        client.commit()
        applied.append(version)
    if applied:
        logger.info("audio migrations applied: %s", applied)
    return applied
