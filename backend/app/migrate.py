import logging
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine
from app.models import Base, Pipeline

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

        if not column_exists(connection, "video_jobs", "pipeline_id"):
            logger.info("Adding pipeline_id to video_jobs")
            connection.execute(
                text(
                    "ALTER TABLE video_jobs "
                    "ADD COLUMN IF NOT EXISTS pipeline_id VARCHAR(36)"
                )
            )

        default_pipeline_id = ensure_default_pipeline(connection)

        if default_pipeline_id is not None:
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
