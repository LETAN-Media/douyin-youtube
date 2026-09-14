import logging
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine
from app.models import Base, Destination, DouyinSource, DouyinVideo, Pipeline, Publication

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

        if not column_exists(connection, "video_jobs", "pipeline_id"):
            logger.info("Adding pipeline_id to video_jobs")
            connection.execute(
                text(
                    "ALTER TABLE video_jobs "
                    "ADD COLUMN IF NOT EXISTS pipeline_id VARCHAR(36)"
                )
            )

        if not column_exists(connection, "pipelines", "youtube_credentials"):
            logger.info("Adding youtube_credentials to pipelines")
            connection.execute(
                text(
                    "ALTER TABLE pipelines "
                    "ADD COLUMN IF NOT EXISTS youtube_credentials TEXT"
                )
            )

        if not column_exists(connection, "pipelines", "youtube_connected"):
            logger.info("Adding youtube_connected to pipelines")
            connection.execute(
                text(
                    "ALTER TABLE pipelines "
                    "ADD COLUMN IF NOT EXISTS youtube_connected BOOLEAN DEFAULT FALSE"
                )
            )

        if not column_exists(connection, "pipelines", "youtube_channel_id"):
            logger.info("Adding youtube_channel_id to pipelines")
            connection.execute(
                text(
                    "ALTER TABLE pipelines "
                    "ADD COLUMN IF NOT EXISTS youtube_channel_id VARCHAR(200)"
                )
            )

        if not column_exists(connection, "pipelines", "youtube_channel_title"):
            logger.info("Adding youtube_channel_title to pipelines")
            connection.execute(
                text(
                    "ALTER TABLE pipelines "
                    "ADD COLUMN IF NOT EXISTS youtube_channel_title VARCHAR(300)"
                )
            )

        if not column_exists(connection, "oauth_states", "pipeline_id"):
            logger.info("Adding pipeline_id to oauth_states")
            connection.execute(
                text(
                    "ALTER TABLE oauth_states "
                    "ADD COLUMN IF NOT EXISTS pipeline_id VARCHAR(36)"
                )
            )

        if not column_exists(connection, "oauth_states", "destination_id"):
            logger.info("Adding destination_id to oauth_states")
            connection.execute(
                text(
                    "ALTER TABLE oauth_states "
                    "ADD COLUMN IF NOT EXISTS destination_id VARCHAR(36)"
                )
            )

        if not column_exists(connection, "video_jobs", "source_video_id"):
            logger.info("Adding source_video_id to video_jobs")
            connection.execute(
                text(
                    "ALTER TABLE video_jobs "
                    "ADD COLUMN IF NOT EXISTS source_video_id VARCHAR(200)"
                )
            )

        if not column_exists(connection, "video_jobs", "schedule_slot_key"):
            logger.info("Adding schedule_slot_key to video_jobs")
            connection.execute(
                text(
                    "ALTER TABLE video_jobs "
                    "ADD COLUMN IF NOT EXISTS schedule_slot_key VARCHAR(100)"
                )
            )

        if not column_exists(connection, "video_jobs", "destination_id"):
            logger.info("Adding destination_id to video_jobs")
            connection.execute(
                text(
                    "ALTER TABLE video_jobs "
                    "ADD COLUMN IF NOT EXISTS destination_id VARCHAR(36)"
                )
            )

        if not column_exists(connection, "douyin_sources", "original_profile_url"):
            logger.info("Adding original_profile_url to douyin_sources")
            connection.execute(
                text(
                    "ALTER TABLE douyin_sources "
                    "ADD COLUMN IF NOT EXISTS original_profile_url TEXT"
                )
            )

        if not column_exists(connection, "douyin_sources", "inventory_sync_status"):
            logger.info("Adding inventory_sync_status to douyin_sources")
            connection.execute(
                text(
                    "ALTER TABLE douyin_sources "
                    "ADD COLUMN IF NOT EXISTS inventory_sync_status VARCHAR(20) DEFAULT 'idle'"
                )
            )

        if not column_exists(connection, "douyin_sources", "destination_id"):
            logger.info("Adding destination_id to douyin_sources")
            connection.execute(
                text(
                    "ALTER TABLE douyin_sources "
                    "ADD COLUMN IF NOT EXISTS destination_id VARCHAR(36)"
                )
            )

        if not column_exists(connection, "douyin_sources", "inventory_count"):
            logger.info("Adding inventory_count to douyin_sources")
            connection.execute(
                text(
                    "ALTER TABLE douyin_sources "
                    "ADD COLUMN IF NOT EXISTS inventory_count INTEGER DEFAULT 0"
                )
            )

        if not column_exists(connection, "douyin_sources", "inventory_synced_at"):
            logger.info("Adding inventory_synced_at to douyin_sources")
            connection.execute(
                text(
                    "ALTER TABLE douyin_sources "
                    "ADD COLUMN IF NOT EXISTS inventory_synced_at TIMESTAMPTZ"
                )
            )

        if not column_exists(connection, "douyin_sources", "inventory_sync_error"):
            logger.info("Adding inventory_sync_error to douyin_sources")
            connection.execute(
                text(
                    "ALTER TABLE douyin_sources "
                    "ADD COLUMN IF NOT EXISTS inventory_sync_error TEXT"
                )
            )

        if not column_exists(connection, "douyin_videos", "is_backfill"):
            logger.info("Adding is_backfill to douyin_videos")
            connection.execute(
                text(
                    "ALTER TABLE douyin_videos "
                    "ADD COLUMN IF NOT EXISTS is_backfill BOOLEAN DEFAULT FALSE"
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
                        f"ADD COLUMN IF NOT EXISTS {column_name} {column_type}"
                    )
                )

        default_pipeline_id = ensure_default_pipeline(connection)

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
            db.commit()
            logger.info(
                "Migrated YouTube OAuth for pipeline %s to destination %s",
                pipeline_id,
                destination.id,
            )
