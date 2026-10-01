import logging
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine
from app.models import (
    Base,
    Destination,
    DouyinSource,
    DouyinVideo,
    Pipeline,
    Publication,
    YouTubeComment,
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


def column_exists(connection: Any, table_name: str, column_name: str) -> bool:
    inspector = inspect(connection)
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def table_exists(connection: Any, table_name: str) -> bool:
    inspector = inspect(connection)
    return inspector.has_table(table_name)


def run_migrations() -> None:
    with engine.begin() as connection:
        if not table_exists(connection, "pipelines"):
            logger.info("Creating pipelines table")
            Base.metadata.create_all(
                bind=connection,
                tables=[Pipeline.__table__],
            )

        if not table_exists(connection, "pipelines"):
            logger.info("Pipelines table already exists via metadata")

        if not table_exists(connection, "douyin_sources"):
            logger.info("Creating douyin_sources table")
            Base.metadata.create_all(
                bind=connection,
                tables=[DouyinSource.__table__],
            )

        if not table_exists(connection, "douyin_videos"):
            logger.info("Creating douyin_videos table")
            Base.metadata.create_all(
                bind=connection,
                tables=[DouyinVideo.__table__],
            )

        if not table_exists(connection, "destinations"):
            logger.info("Creating destinations table")
            Base.metadata.create_all(
                bind=connection,
                tables=[Destination.__table__],
            )

        if not table_exists(connection, "publications"):
            logger.info("Creating publications table")
            Base.metadata.create_all(
                bind=connection,
                tables=[Publication.__table__],
            )

        if not table_exists(connection, "douyin_sessions"):
            from app.models import DouyinSession

            logger.info("Creating douyin_sessions table")
            Base.metadata.create_all(
                bind=connection,
                tables=[DouyinSession.__table__],
            )

        # Shared PlatformAccount + generic PipelineSource (isolated transactions)
        try:
            from app.models import PlatformAccount, PipelineSource

            if not table_exists(connection, "platform_accounts"):
                logger.info("Creating platform_accounts table")
                Base.metadata.create_all(bind=connection, tables=[PlatformAccount.__table__])
            if not table_exists(connection, "pipeline_sources"):
                logger.info("Creating pipeline_sources table")
                Base.metadata.create_all(bind=connection, tables=[PipelineSource.__table__])
        except Exception as exc:
            logger.warning("Platform tables create skipped: %s", exc)

        # YouTube Analytics + Trend Research + Content DNA tables (additive only)
        try:
            from app.models import (
                YouTubeChannelAnalyticsDaily,
                YouTubeChannelDNA,
                YouTubeContentFingerprint,
                YouTubeDailyPublishOverride,
                YouTubeDNASuggestion,
                YouTubePerformanceSnapshot,
                YouTubeResearchItem,
                YouTubeResearchRun,
                YouTubeVideoAnalyticsDaily,
            )

            for _model in (
                YouTubeChannelAnalyticsDaily,
                YouTubeVideoAnalyticsDaily,
                YouTubeResearchRun,
                YouTubeResearchItem,
                YouTubeChannelDNA,
                YouTubeContentFingerprint,
                YouTubePerformanceSnapshot,
                YouTubeDNASuggestion,
                YouTubeDailyPublishOverride,
            ):
                if not table_exists(connection, _model.__table__.name):
                    logger.info("Creating %s table", _model.__table__.name)
                    Base.metadata.create_all(
                        bind=connection, tables=[_model.__table__]
                    )
        except Exception as exc:
            logger.warning("Analytics tables create skipped: %s", exc)
        # YouTube counts can exceed int32 (viral videos > 2.1B views).
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
            try:
                with connection.begin_nested():
                    connection.execute(
                        text(
                            f"ALTER TABLE {_tbl} ALTER COLUMN {_col} TYPE BIGINT"
                        )
                    )
            except Exception:
                logger.info("bigint %s.%s skipped", _tbl, _col)
        for _tbl, _col, _typ in [
            ("destinations", "research_region", "VARCHAR(10) DEFAULT 'VN'"),
        ]:
            try:
                if not column_exists(connection, _tbl, _col):
                    logger.info("Adding %s to %s", _col, _tbl)
                    with connection.begin_nested():
                        connection.execute(text(f"ALTER TABLE {_tbl} ADD COLUMN {_col} {_typ}"))
            except Exception as exc:
                logger.warning("Add %s to %s skipped: %s", _col, _tbl, exc)
        for _tbl, _col, _typ in [
            ("douyin_sources", "platform", "VARCHAR(20) DEFAULT 'douyin'"),
            ("douyin_sources", "avatar_url", "TEXT"),
            ("douyin_sources", "priority", "INTEGER DEFAULT 0"),
            ("platform_accounts", "needs_reauth", "BOOLEAN DEFAULT FALSE"),
            ("pipeline_sources", "last_error", "TEXT"),
        ]:
            try:
                if not column_exists(connection, _tbl, _col):
                    logger.info("Adding %s to %s", _col, _tbl)
                    with connection.begin_nested():
                        connection.execute(text(f"ALTER TABLE {_tbl} ADD COLUMN {_col} {_typ}"))
            except Exception as exc:
                logger.warning("Add %s to %s skipped: %s", _col, _tbl, exc)
        # One-time per-source cookie → global PlatformAccount
        try:
            has_cookie = connection.execute(text("SELECT cookie_encrypted FROM douyin_sources WHERE cookie_encrypted IS NOT NULL LIMIT 1")).fetchone()
            if has_cookie is not None:
                exists = connection.execute(text("SELECT 1 FROM platform_accounts WHERE platform='douyin' LIMIT 1")).fetchone()
                if exists is None:
                    logger.info("Migrating per-source Douyin cookie to global PlatformAccount")
                    connection.execute(
                        text(
                            "INSERT INTO platform_accounts (id, platform, display_name, status, credentials_encrypted, created_at, updated_at) "
                            "VALUES (:id, 'douyin', 'Douyin', 'connected', :creds, NOW(), NOW()) ON CONFLICT (platform) DO NOTHING"
                        ),
                        {"id": str(__import__("uuid").uuid4()), "creds": has_cookie[0]},
                    )
        except Exception as exc:
            logger.warning("PlatformAccount cookie migration skipped: %s", exc)

        if not column_exists(connection, "video_jobs", "pipeline_id"):
            logger.info("Adding pipeline_id to video_jobs")
            with connection.begin_nested():
                connection.execute(
                    text(
                        "ALTER TABLE video_jobs "
                    "ADD COLUMN pipeline_id VARCHAR(36)"
                )
            )

        if not column_exists(connection, "pipelines", "youtube_credentials"):
            logger.info("Adding youtube_credentials to pipelines")
            with connection.begin_nested():
                connection.execute(
                    text(
                        "ALTER TABLE pipelines "
                    "ADD COLUMN youtube_credentials TEXT"
                )
            )

        if not column_exists(connection, "pipelines", "youtube_connected"):
            logger.info("Adding youtube_connected to pipelines")
            with connection.begin_nested():
                connection.execute(
                    text(
                        "ALTER TABLE pipelines "
                    "ADD COLUMN youtube_connected BOOLEAN DEFAULT FALSE"
                )
            )

        if not column_exists(connection, "pipelines", "youtube_channel_id"):
            logger.info("Adding youtube_channel_id to pipelines")
            with connection.begin_nested():
                connection.execute(
                    text(
                        "ALTER TABLE pipelines "
                    "ADD COLUMN youtube_channel_id VARCHAR(200)"
                )
            )

        if not column_exists(connection, "pipelines", "youtube_channel_title"):
            logger.info("Adding youtube_channel_title to pipelines")
            with connection.begin_nested():
                connection.execute(
                    text(
                        "ALTER TABLE pipelines "
                    "ADD COLUMN youtube_channel_title VARCHAR(300)"
                )
            )

        if not column_exists(connection, "oauth_states", "pipeline_id"):
            logger.info("Adding pipeline_id to oauth_states")
            with connection.begin_nested():
                connection.execute(
                    text(
                        "ALTER TABLE oauth_states "
                    "ADD COLUMN pipeline_id VARCHAR(36)"
                )
            )

        if not column_exists(connection, "oauth_states", "destination_id"):
            logger.info("Adding destination_id to oauth_states")
            with connection.begin_nested():
                connection.execute(
                    text(
                        "ALTER TABLE oauth_states "
                    "ADD COLUMN destination_id VARCHAR(36)"
                )
            )

        if not column_exists(connection, "video_jobs", "source_video_id"):
            logger.info("Adding source_video_id to video_jobs")
            with connection.begin_nested():
                connection.execute(
                    text(
                        "ALTER TABLE video_jobs "
                    "ADD COLUMN source_video_id VARCHAR(200)"
                )
            )

        if not column_exists(connection, "video_jobs", "schedule_slot_key"):
            logger.info("Adding schedule_slot_key to video_jobs")
            with connection.begin_nested():
                connection.execute(
                    text(
                        "ALTER TABLE video_jobs "
                    "ADD COLUMN schedule_slot_key VARCHAR(100)"
                )
            )

        if not column_exists(connection, "video_jobs", "destination_id"):
            logger.info("Adding destination_id to video_jobs")
            with connection.begin_nested():
                connection.execute(
                    text(
                        "ALTER TABLE video_jobs "
                    "ADD COLUMN destination_id VARCHAR(36)"
                )
            )

        if not column_exists(connection, "video_jobs", "publication_id"):
            logger.info("Adding publication_id to video_jobs")
            with connection.begin_nested():
                connection.execute(
                    text(
                        "ALTER TABLE video_jobs "
                    "ADD COLUMN publication_id VARCHAR(36)"
                )
            )
            try:
                connection.execute(
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

        for _col, _typ in [
            ("last_scheduler_check_at", "TIMESTAMPTZ"),
            ("last_cycle_at", "TIMESTAMPTZ"),
            ("last_job_created_at", "TIMESTAMPTZ"),
            ("last_skip_reason", "TEXT"),
        ]:
            if not column_exists(connection, "destinations", _col):
                logger.info("Adding %s to destinations", _col)
                connection.execute(
                    text(
                        f"ALTER TABLE destinations "
                        f"ADD COLUMN {_col} {_typ}"
                    )
                )

        if not column_exists(connection, "douyin_sources", "original_profile_url"):
            logger.info("Adding original_profile_url to douyin_sources")
            with connection.begin_nested():
                connection.execute(
                    text(
                        "ALTER TABLE douyin_sources "
                    "ADD COLUMN original_profile_url TEXT"
                )
            )

        if not column_exists(connection, "douyin_sources", "inventory_sync_status"):
            logger.info("Adding inventory_sync_status to douyin_sources")
            with connection.begin_nested():
                connection.execute(
                    text(
                        "ALTER TABLE douyin_sources "
                    "ADD COLUMN inventory_sync_status VARCHAR(20) DEFAULT 'idle'"
                )
            )

        if not column_exists(connection, "douyin_sources", "destination_id"):
            logger.info("Adding destination_id to douyin_sources")
            with connection.begin_nested():
                connection.execute(
                    text(
                        "ALTER TABLE douyin_sources "
                    "ADD COLUMN destination_id VARCHAR(36)"
                )
            )

        if not column_exists(connection, "douyin_sources", "inventory_count"):
            logger.info("Adding inventory_count to douyin_sources")
            with connection.begin_nested():
                connection.execute(
                    text(
                        "ALTER TABLE douyin_sources "
                    "ADD COLUMN inventory_count INTEGER DEFAULT 0"
                )
            )

        if not column_exists(connection, "douyin_sources", "inventory_synced_at"):
            logger.info("Adding inventory_synced_at to douyin_sources")
            with connection.begin_nested():
                connection.execute(
                    text(
                        "ALTER TABLE douyin_sources "
                    "ADD COLUMN inventory_synced_at TIMESTAMPTZ"
                )
            )

        if not column_exists(connection, "douyin_sources", "inventory_sync_error"):
            logger.info("Adding inventory_sync_error to douyin_sources")
            with connection.begin_nested():
                connection.execute(
                    text(
                        "ALTER TABLE douyin_sources "
                    "ADD COLUMN inventory_sync_error TEXT"
                )
            )

        # ---- AUTO mode: per-source cookie + scan policy ----
        for column_name, column_type in [
            ("cookie_encrypted", "TEXT"),
            ("cookie_status", "VARCHAR(20) DEFAULT 'missing'"),
            ("cookie_account_name", "VARCHAR(300)"),
            ("cookie_verified_at", "TIMESTAMPTZ"),
            ("needs_reauth", "BOOLEAN DEFAULT FALSE"),
            ("scan_interval_minutes", "INTEGER DEFAULT 15"),
            ("max_videos_per_day", "INTEGER DEFAULT 50"),
            ("include_keywords", "JSON"),
            ("exclude_keywords", "JSON"),
            ("next_scan_at", "TIMESTAMPTZ"),
            ("last_scan_at", "TIMESTAMPTZ"),
            ("start_mode", "VARCHAR(20) DEFAULT 'new_only'"),
            ("initial_limit", "INTEGER DEFAULT 10"),
            ("baseline_done", "BOOLEAN DEFAULT FALSE"),
            ("borderline_policy", "VARCHAR(20) DEFAULT 'hold'"),
            ("mismatch_policy", "VARCHAR(20) DEFAULT 'reject'"),
            ('"order"', "VARCHAR(20) DEFAULT 'oldest_first'"),
        ]:
            if not column_exists(connection, "douyin_sources", column_name.strip('"')):
                logger.info("Adding %s to douyin_sources", column_name)
                connection.execute(
                    text(
                        "ALTER TABLE douyin_sources "
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )

        # ---- admin-driven Douyin discovery (no scheduled scanning) ----
        for column_name, column_type in [
            ("feed_provider", "VARCHAR(50) DEFAULT 'rapidapi_justone'"),
            ("initial_import_status", "VARCHAR(20) DEFAULT 'pending'"),
            ("initial_import_cursor", "VARCHAR(64)"),
            ("initial_import_pages", "INTEGER DEFAULT 0"),
            ("initial_import_videos", "INTEGER DEFAULT 0"),
            ("initial_import_last_error", "TEXT"),
            ("initial_import_started_at", "TIMESTAMPTZ"),
            ("initial_import_completed_at", "TIMESTAMPTZ"),
            ("last_refresh_at", "TIMESTAMPTZ"),
            ("provider_status", "VARCHAR(30) DEFAULT 'ok'"),
            ("provider_status_detail", "TEXT"),
        ]:
            if not column_exists(connection, "douyin_sources", column_name):
                logger.info("Adding %s to douyin_sources", column_name)
                connection.execute(
                    text(
                        "ALTER TABLE douyin_sources "
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )

        # Existing sources already scanned under the old monitor are treated as
        # completed so the UI does not offer them a first-time import.
        try:
            connection.execute(
                text(
                    "UPDATE douyin_sources SET initial_import_status = 'completed' "
                    "WHERE initial_import_status = 'pending' AND ("
                    "inventory_count > 0 OR last_scan_at IS NOT NULL "
                    "OR inventory_synced_at IS NOT NULL)"
                )
            )
        except Exception:
            logger.info("initial_import_status backfill skipped")

        for column_name, column_type in [
            ("match_level", "VARCHAR(20)"),
            ("hold_reason", "TEXT"),
        ]:
            if not column_exists(connection, "douyin_videos", column_name):
                logger.info("Adding %s to douyin_videos", column_name)
                connection.execute(
                    text(
                        "ALTER TABLE douyin_videos "
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )

        if not column_exists(connection, "destinations", "min_upload_interval_minutes"):
            logger.info("Adding min_upload_interval_minutes to destinations")
            with connection.begin_nested():
                connection.execute(
                    text(
                        "ALTER TABLE destinations "
                    "ADD COLUMN min_upload_interval_minutes INTEGER DEFAULT 0"
                )
            )

        # ---- AI Comment Reply (isolated from the metadata prompt) ----
        # Additive only: new comment_* columns on destinations. The existing
        # prompt_override/metadata_* columns that feed title/description/
        # hashtags are never renamed or touched.
        for column_name, column_type in [
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
            ("last_comment_scan_at", "TIMESTAMPTZ"),
        ]:
            if not column_exists(connection, "destinations", column_name):
                logger.info("Adding %s to destinations", column_name)
                connection.execute(
                    text(
                        "ALTER TABLE destinations "
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )

        if not table_exists(connection, "youtube_comments"):
            logger.info("Creating youtube_comments table")
            Base.metadata.create_all(
                bind=connection,
                tables=[YouTubeComment.__table__],
            )

        # Existing sources with prior scans keep flowing: mark their baseline
        # as done so the NEW_ONLY first-sync policy only affects new sources.
        try:
            connection.execute(
                text(
                    "UPDATE douyin_sources SET baseline_done = TRUE "
                    "WHERE baseline_done = FALSE AND ("
                    "inventory_count > 0 OR last_scan_at IS NOT NULL "
                    "OR inventory_synced_at IS NOT NULL)"
                )
            )
        except Exception:
            logger.info("baseline_done backfill skipped")

        # Dedupe (source_id, video_id) then enforce uniqueness so an aweme
        # is never enqueued twice for the same source.
        try:
            dupes = connection.execute(
                text(
                    "SELECT source_id, video_id, COUNT(*) c FROM douyin_videos "
                    "WHERE source_id IS NOT NULL "
                    "GROUP BY source_id, video_id HAVING COUNT(*) > 1"
                )
            ).fetchall()
            for row in dupes:
                connection.execute(
                    text(
                        "DELETE FROM douyin_videos a USING douyin_videos b "
                        "WHERE a.id > b.id "
                        "AND a.source_id = :sid AND b.source_id = :sid "
                        "AND a.video_id = :vid AND b.video_id = :vid"
                    ),
                    {"sid": row[0], "vid": row[1]},
                )
            with connection.begin_nested():
                connection.execute(
                    text(
                        "ALTER TABLE douyin_videos "
                    "ADD CONSTRAINT uq_douyin_video_source_video "
                    "UNIQUE (source_id, video_id)"
                )
            )
        except Exception:
            logger.info("Unique (source_id, video_id) already exists or skipped")

        if not column_exists(connection, "douyin_videos", "is_backfill"):
            logger.info("Adding is_backfill to douyin_videos")
            with connection.begin_nested():
                connection.execute(
                    text(
                        "ALTER TABLE douyin_videos "
                    "ADD COLUMN is_backfill BOOLEAN DEFAULT FALSE"
                )
            )

        if not column_exists(connection, "douyin_videos", "thumbnail_url"):
            logger.info("Adding thumbnail_url to douyin_videos")
            with connection.begin_nested():
                connection.execute(
                    text(
                        "ALTER TABLE douyin_videos "
                    "ADD COLUMN thumbnail_url TEXT"
                )
            )

        try:
            connection.execute(
                text("ALTER TABLE douyin_videos ALTER COLUMN source_id DROP NOT NULL")
            )
        except Exception:
            pass

        if not column_exists(connection, "publications", "publication_mode"):
            logger.info("Adding publication_mode to publications")
            with connection.begin_nested():
                connection.execute(
                    text(
                        "ALTER TABLE publications "
                    "ADD COLUMN publication_mode VARCHAR(20) DEFAULT 'auto'"
                )
            )

        pipeline_columns = [
            ("daily_upload_limit", "INTEGER DEFAULT 6"),
            ("upload_slots", "JSON"),
            ("backlog_slots_per_day", "INTEGER DEFAULT 4"),
            ("new_slots_per_day", "INTEGER DEFAULT 2"),
            ("backlog_order", "VARCHAR(10) DEFAULT 'asc'"),
            ("source_selection_strategy", "VARCHAR(50) DEFAULT 'round_robin'"),
            ("source_selection_cursor", "INTEGER DEFAULT 0"),
            ("backlog_threshold_days", "INTEGER DEFAULT 7"),
            ("timezone", "VARCHAR(50) DEFAULT 'UTC'"),
        ]

        for column_name, column_type in pipeline_columns:
            if not column_exists(connection, "pipelines", column_name):
                logger.info("Adding %s to pipelines", column_name)
                connection.execute(
                    text(
                        "ALTER TABLE pipelines "
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )

        # ---- Native YouTube Scheduled Publishing (additive only) ----
        for column_name, column_type in [
            ("youtube_default_publish_mode", "VARCHAR(20) DEFAULT 'immediate'"),
        ]:
            if not column_exists(connection, "destinations", column_name):
                logger.info("Adding %s to destinations", column_name)
                connection.execute(
                    text(
                        "ALTER TABLE destinations "
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )

        for column_name, column_type in [
            ("youtube_publish_mode", "VARCHAR(20) DEFAULT 'immediate'"),
            ("youtube_publish_at", "TIMESTAMPTZ"),
            ("youtube_schedule_timezone", "VARCHAR(50) DEFAULT 'Asia/Ho_Chi_Minh'"),
            ("youtube_scheduled", "BOOLEAN DEFAULT FALSE"),
            ("youtube_actual_published_at", "TIMESTAMPTZ"),
            ("youtube_privacy_status", "VARCHAR(20)"),
        ]:
            if not column_exists(connection, "publications", column_name):
                logger.info("Adding %s to publications", column_name)
                connection.execute(
                    text(
                        "ALTER TABLE publications "
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )

        for column_name, column_type in [
            ("youtube_publish_mode", "VARCHAR(20) DEFAULT 'immediate'"),
            ("youtube_publish_at", "TIMESTAMPTZ"),
            ("youtube_schedule_timezone", "VARCHAR(50) DEFAULT 'Asia/Ho_Chi_Minh'"),
            ("youtube_scheduled", "BOOLEAN DEFAULT FALSE"),
            ("youtube_actual_published_at", "TIMESTAMPTZ"),
        ]:
            if not column_exists(connection, "video_jobs", column_name):
                logger.info("Adding %s to video_jobs", column_name)
                connection.execute(
                    text(
                        "ALTER TABLE video_jobs "
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )

        if not column_exists(connection, "pipelines", "youtube_default_publish_mode"):
            logger.info("Adding youtube_default_publish_mode to pipelines")
            connection.execute(
                text(
                    "ALTER TABLE pipelines "
                    "ADD COLUMN youtube_default_publish_mode VARCHAR(20) DEFAULT 'immediate'"
                )
            )

        # Backfill: existing rows keep immediate semantics.
        try:
            connection.execute(
                text(
                    "UPDATE publications SET youtube_publish_mode='immediate' "
                    "WHERE youtube_publish_mode IS NULL"
                )
            )
            connection.execute(
                text(
                    "UPDATE video_jobs SET youtube_publish_mode='immediate' "
                    "WHERE youtube_publish_mode IS NULL"
                )
            )
            connection.execute(
                text(
                    "UPDATE destinations SET youtube_default_publish_mode='immediate' "
                    "WHERE youtube_default_publish_mode IS NULL"
                )
            )
        except Exception:
            logger.info("youtube publish mode backfill skipped")

        # Dashboard latency: per-pipeline GROUP BY needs pipeline_id indexes.
        # Additive only, IF NOT EXISTS, safe on small tables.
        for _idx, _tbl, _col in [
            ("ix_video_jobs_pipeline_id", "video_jobs", "pipeline_id"),
            ("ix_publications_pipeline_id", "publications", "pipeline_id"),
            ("ix_douyin_videos_pipeline_id", "douyin_videos", "pipeline_id"),
            ("ix_douyin_sources_pipeline_id", "douyin_sources", "pipeline_id"),
            ("ix_destinations_pipeline_id", "destinations", "pipeline_id"),
        ]:
            try:
                connection.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS {_idx} "
                        f"ON {_tbl} ({_col})"
                    )
                )
            except Exception:
                logger.info("index %s skipped", _idx)

        # Shorts slot reservation: one reservation per channel per minute.
        # NULL scheduled_at rows stay distinct; legacy duplicates only log.
        try:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "uq_publication_destination_scheduled_at "
                    "ON publications (destination_id, scheduled_at)"
                )
            )
        except Exception:
            logger.info("slot unique index skipped (possible legacy duplicates)")

        default_pipeline_id = ensure_default_pipeline(connection)

        # ---- Multi-tenant auth + workspace backfill (additive, idempotent) ----
        try:
            run_tenant_migration(connection)
        except Exception as exc:
            logger.warning("Tenant migration skipped/partial: %s", exc)

        if default_pipeline_id is not None:
            migrate_existing_youtube_to_destination(connection)
            assign_existing_jobs_to_default(connection, default_pipeline_id)


def ensure_default_pipeline(connection: Any) -> str | None:
    with Session(bind=connection) as db:
        pipeline = db.execute(
            text(
                "SELECT id FROM pipelines "
                "WHERE slug = :slug "
                "LIMIT 1"
            ),
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
        logger.info(
            "Created default pipeline id=%s name=%s",
            pipeline_id,
            DEFAULT_PIPELINE_NAME,
        )
        return pipeline_id


def assign_existing_jobs_to_default(connection: Any, default_pipeline_id: str) -> None:
    with Session(bind=connection) as db:
        result = db.execute(
            text(
                "UPDATE video_jobs "
                "SET pipeline_id = :pipeline_id "
                "WHERE pipeline_id IS NULL"
            ),
            {"pipeline_id": default_pipeline_id},
        )
        db.commit()
        logger.info(
            "Assigned %s existing jobs to default pipeline",
            result.rowcount,
        )


def migrate_existing_youtube_to_destination(connection: Any) -> None:
    with Session(bind=connection) as db:
        pipelines = db.execute(
            text(
                "SELECT id, youtube_channel_title, youtube_credentials, youtube_channel_id "
                "FROM pipelines "
                "WHERE youtube_credentials IS NOT NULL "
                "AND youtube_channel_id IS NOT NULL"
            ),
        ).fetchall()

        for row in pipelines:
            pipeline_id = row[0]
            channel_title = row[1]
            credentials = row[2]
            channel_id = row[3]

            existing = db.execute(
                text(
                    "SELECT id FROM destinations "
                    "WHERE pipeline_id = :pipeline_id "
                    "AND platform = 'youtube' "
                    "LIMIT 1"
                ),
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
            # New destinations inherit the pipeline workspace (never global).
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
            logger.info(
                "Migrated YouTube OAuth for pipeline %s to destination %s",
                pipeline_id,
                destination.id,
            )


# =====================================================================
# Multi-tenant migration (Phase 2-3): additive + idempotent + backfill.
# Every step uses IF NOT EXISTS / ON CONFLICT guards so reruns are safe.
# =====================================================================

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


def run_tenant_migration(connection: Any) -> None:
    from app.models import User, UserSession, Workspace, WorkspaceMember

    # 1. New auth tables (no-op when they already exist).
    for _model in (User, Workspace, WorkspaceMember, UserSession):
        if not table_exists(connection, _model.__table__.name):
            logger.info("Creating %s table", _model.__table__.name)
            Base.metadata.create_all(bind=connection, tables=[_model.__table__])

    # 2. workspace_id columns on every tenant table.
    for _tbl in _TENANT_TABLES:
        try:
            if table_exists(connection, _tbl) and not column_exists(
                connection, _tbl, "workspace_id"
            ):
                logger.info("Adding workspace_id to %s", _tbl)
                connection.execute(
                    text(
                        f"ALTER TABLE {_tbl} "
                        "ADD COLUMN workspace_id VARCHAR(36)"
                    )
                )
                connection.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS ix_{_tbl}_workspace_id "
                        f"ON {_tbl} (workspace_id)"
                    )
                )
        except Exception as exc:
            logger.warning("workspace_id on %s skipped: %s", _tbl, exc)
    try:
        if table_exists(connection, "oauth_states") and not column_exists(
            connection, "oauth_states", "initiated_by_user_id"
        ):
            connection.execute(
                text(
                    "ALTER TABLE oauth_states "
                    "ADD COLUMN initiated_by_user_id VARCHAR(36)"
                )
            )
    except Exception as exc:
        logger.warning("oauth_states.initiated_by_user_id skipped: %s", exc)

    # 3. Composite indexes for the hottest scoped queries.
    for _idx, _tbl, _cols in [
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
    ]:
        try:
            if table_exists(connection, _tbl):
                connection.execute(
                    text(f"CREATE INDEX IF NOT EXISTS {_idx} ON {_tbl} {_cols}")
                )
        except Exception:
            logger.info("index %s skipped", _idx)

    # 4. Ensure the Admin Workspace exists (owns ALL pre-existing data).
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    _now = _dt.now(_tz.utc)
    admin_ws_id = connection.execute(
        text("SELECT id FROM workspaces WHERE name = :name LIMIT 1"),
        {"name": ADMIN_WORKSPACE_NAME},
    ).fetchone()
    if admin_ws_id is None:
        import uuid as _uuid

        admin_ws_id = (str(_uuid.uuid4()),)
        connection.execute(
            text(
                "INSERT INTO workspaces (id, name, owner_user_id, created_at, updated_at) "
                "VALUES (:id, :name, NULL, :now, :now)"
            ),
            {"id": admin_ws_id[0], "name": ADMIN_WORKSPACE_NAME, "now": _now},
        )
        logger.info("Created Admin Workspace id=%s", admin_ws_id[0])
    admin_ws_id = admin_ws_id[0]

    # 5. Backfill pipelines first (root of the tenant tree).
    if table_exists(connection, "pipelines"):
        connection.execute(
            text(
                "UPDATE pipelines SET workspace_id = :ws "
                "WHERE workspace_id IS NULL"
            ),
            {"ws": admin_ws_id},
        )

    # 6. Backfill direct children of pipelines.
    for _tbl in (
        "destinations",
        "pipeline_sources",
        "douyin_sources",
        "douyin_videos",
        "publications",
        "video_jobs",
    ):
        try:
            if not table_exists(connection, _tbl):
                continue
            if _tbl == "video_jobs":
                # Jobs may hang off pipeline OR destination.
                connection.execute(
                    text(
                        "UPDATE video_jobs SET workspace_id = pipelines.workspace_id "
                        "FROM pipelines WHERE video_jobs.workspace_id IS NULL "
                        "AND video_jobs.pipeline_id = pipelines.id"
                    )
                )
                connection.execute(
                    text(
                        "UPDATE video_jobs SET workspace_id = destinations.workspace_id "
                        "FROM destinations WHERE video_jobs.workspace_id IS NULL "
                        "AND video_jobs.destination_id = destinations.id"
                    )
                )
            elif _tbl == "publications":
                connection.execute(
                    text(
                        "UPDATE publications SET workspace_id = pipelines.workspace_id "
                        "FROM pipelines WHERE publications.workspace_id IS NULL "
                        "AND publications.pipeline_id = pipelines.id"
                    )
                )
                connection.execute(
                    text(
                        "UPDATE publications SET workspace_id = destinations.workspace_id "
                        "FROM destinations WHERE publications.workspace_id IS NULL "
                        "AND publications.destination_id = destinations.id"
                    )
                )
            elif _tbl in ("destinations", "pipeline_sources", "douyin_sources", "douyin_videos"):
                connection.execute(
                    text(
                        f"UPDATE {_tbl} SET workspace_id = pipelines.workspace_id "
                        f"FROM pipelines WHERE {_tbl}.workspace_id IS NULL "
                        f"AND {_tbl}.pipeline_id = pipelines.id"
                    )
                )
            # Any row that still has no workspace (orphan) falls into Admin.
            connection.execute(
                text(f"UPDATE {_tbl} SET workspace_id = :ws WHERE workspace_id IS NULL"),
                {"ws": admin_ws_id},
            )
        except Exception as exc:
            logger.warning("Backfill %s skipped: %s", _tbl, exc)

    # 7. Backfill destination-scoped tables.
    for _tbl in (
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
        try:
            if not table_exists(connection, _tbl):
                continue
            connection.execute(
                text(
                    f"UPDATE {_tbl} SET workspace_id = destinations.workspace_id "
                    f"FROM destinations WHERE {_tbl}.workspace_id IS NULL "
                    f"AND {_tbl}.destination_id = destinations.id"
                )
            )
            if _tbl == "youtube_research_items":
                connection.execute(
                    text(
                        "UPDATE youtube_research_items SET workspace_id = "
                        "youtube_research_runs.workspace_id "
                        "FROM youtube_research_runs "
                        "WHERE youtube_research_items.workspace_id IS NULL "
                        "AND youtube_research_items.run_id = youtube_research_runs.id"
                    )
                )
            if _tbl == "youtube_content_fingerprints":
                connection.execute(
                    text(
                        "UPDATE youtube_content_fingerprints SET workspace_id = "
                        "publications.workspace_id FROM publications "
                        "WHERE youtube_content_fingerprints.workspace_id IS NULL "
                        "AND youtube_content_fingerprints.publication_id = publications.id"
                    )
                )
            connection.execute(
                text(f"UPDATE {_tbl} SET workspace_id = :ws WHERE workspace_id IS NULL"),
                {"ws": admin_ws_id},
            )
        except Exception as exc:
            logger.warning("Backfill %s skipped: %s", _tbl, exc)

    # 8. Optional bootstrap of the first system-admin user from env.
    try:
        admin_email = (settings.admin_email or "").strip().lower()
        admin_pw = settings.admin_initial_password or ""
        if admin_email and admin_pw:
            exists = connection.execute(
                text("SELECT 1 FROM users WHERE email = :email LIMIT 1"),
                {"email": admin_email},
            ).fetchone()
            if exists is None:
                from app.auth import hash_password as _hash_pw

                import uuid as _uuid

                uid = str(_uuid.uuid4())
                connection.execute(
                    text(
                        "INSERT INTO users (id, email, password_hash, display_name, "
                        "status, is_system_admin, created_at, updated_at) "
                        "VALUES (:id, :email, :pw, 'System Admin', 'active', TRUE, :now, :now)"
                    ),
                    {"id": uid, "email": admin_email, "pw": _hash_pw(admin_pw), "now": _now},
                )
                connection.execute(
                    text(
                        "INSERT INTO workspace_members (id, workspace_id, user_id, role, created_at) "
                        "VALUES (:id, :ws, :uid, 'owner', :now) "
                        "ON CONFLICT (workspace_id, user_id) DO NOTHING"
                    ),
                    {"id": str(_uuid.uuid4()), "ws": admin_ws_id, "uid": uid, "now": _now},
                )
                logger.info("Bootstrapped system admin user %s", admin_email)
    except Exception as exc:
        logger.warning("Admin bootstrap skipped: %s", exc)
