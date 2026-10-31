"""Delete one Douyin pipeline and every management row that belongs to it.

Why this module exists
----------------------
``db.delete(pipeline)`` is not safe. ``Pipeline.sources/videos/destinations/
publications`` have no ORM cascade, so SQLAlchemy's unit of work nulls the
child foreign keys before deleting the parent. ``destinations.pipeline_id``,
``douyin_videos.pipeline_id`` and ``publications.pipeline_id`` are NOT NULL,
which raises ``IntegrityError`` (HTTP 500). Relying on ``ON DELETE CASCADE``
is not enough either: ``video_jobs`` and ``oauth_states`` use
``ON DELETE SET NULL`` (the queue would be orphaned), and SQLite/libSQL only
enforces foreign keys when the pragma is enabled.

Deletion therefore happens here, explicitly and child-first:

1. preflight: refuse while an upload/download is in flight or its outcome is
   unknown, so reconciliation data is never destroyed;
2. disable the pipeline and its destinations in a committed step, so the
   scheduler cannot create new jobs and the worker cannot start new uploads;
3. delete every pipeline-scoped row in foreign-key order, always filtered by
   ids collected from this pipeline only (never another pipeline/workspace);
4. verify no row still references those ids, then delete the pipeline itself
   and commit once. Any failure rolls back and restores the enabled flags.

YouTube uploads are never touched: this only removes internal management
rows. Published videos keep existing on YouTube.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, inspect, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import Base
from app.models import (
    AppSetting,
    Destination,
    DouyinSource,
    DouyinVideo,
    Pipeline,
    PipelineSource,
    Publication,
    VideoJob,
    YouTubeResearchRun,
)

logger = logging.getLogger("douyin-youtube-pipeline-delete")

# An upload that is running — or whose result is not known — must never be
# deleted: the worker/reconciliation still needs those rows to recover.
BLOCKING_JOB_STATUSES = (
    "downloading",
    "uploading",
    "upload_unknown",
    "processing",
    "ai_metadata",
)
BLOCKING_PUBLICATION_STATUSES = (
    "downloading",
    "uploading",
    "upload_unknown",
    "processing",
    "ai_metadata",
)

# Shared/system tables that must never be touched by a pipeline purge.
PROTECTED_TABLES = {
    "users",
    "user_sessions",
    "workspaces",
    "workspace_members",
    "platform_accounts",
}


class PipelineDeleteError(Exception):
    """API-facing failure with an explicit code and HTTP status."""

    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(f"{code}: {message}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _existing_tables(db: Session) -> set[str]:
    try:
        return set(inspect(db.get_bind()).get_table_names())
    except Exception:
        # Schema introspection is best effort; model tables still get deleted
        # and a missing table simply matches nothing.
        return set(Base.metadata.tables)


def _delete_rows(
    db: Session,
    table_name: str,
    conditions: list[tuple[str, list[str]]],
    tables: set[str],
) -> int:
    table = Base.metadata.tables.get(table_name)
    if table is None or table_name not in tables:
        return 0
    clauses = []
    for column, values in conditions:
        if not values or column not in table.c:
            continue
        clauses.append(table.c[column].in_(list(values)))
    if not clauses:
        return 0
    result = db.execute(
        delete(table)
        .where(or_(*clauses))
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def _ids(db: Session, stmt) -> list[str]:
    return [str(row) for row in db.execute(stmt).scalars().all() if row]


def collect_pipeline_ids(db: Session, pipeline_id: str) -> dict[str, list[str]]:
    """Ids of everything that belongs to *this* pipeline only."""
    destination_ids = _ids(
        db, select(Destination.id).where(Destination.pipeline_id == pipeline_id)
    )
    source_ids = _ids(
        db, select(DouyinSource.id).where(DouyinSource.pipeline_id == pipeline_id)
    )
    if destination_ids:
        source_ids += _ids(
            db,
            select(DouyinSource.id).where(
                DouyinSource.destination_id.in_(destination_ids)
            ),
        )
    video_ids = _ids(
        db, select(DouyinVideo.id).where(DouyinVideo.pipeline_id == pipeline_id)
    )
    if source_ids:
        video_ids += _ids(
            db,
            select(DouyinVideo.id).where(DouyinVideo.source_id.in_(source_ids)),
        )
    publication_ids = _ids(
        db, select(Publication.id).where(Publication.pipeline_id == pipeline_id)
    )
    for column, values in (
        (Publication.destination_id, destination_ids),
        (Publication.douyin_video_id, video_ids),
    ):
        if values:
            publication_ids += _ids(
                db, select(Publication.id).where(column.in_(values))
            )
    job_ids = _ids(
        db, select(VideoJob.id).where(VideoJob.pipeline_id == pipeline_id)
    )
    for column, values in (
        (VideoJob.destination_id, destination_ids),
        (VideoJob.publication_id, publication_ids),
    ):
        if values:
            job_ids += _ids(db, select(VideoJob.id).where(column.in_(values)))
    research_run_ids = []
    if destination_ids:
        research_run_ids = _ids(
            db,
            select(YouTubeResearchRun.id).where(
                YouTubeResearchRun.destination_id.in_(destination_ids)
            ),
        )
    unique = lambda items: sorted(set(items))  # noqa: E731
    return {
        "pipeline": [pipeline_id],
        "dest": unique(destination_ids),
        "src": unique(source_ids),
        "video": unique(video_ids),
        "pub": unique(publication_ids),
        "job": unique(job_ids),
        "run": unique(research_run_ids),
    }


# Child-first order. Every step is scoped by ids that belong to this pipeline,
# so another pipeline/workspace can never be reached.
PURGE_STEPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Rows referencing publications / destinations.
    ("youtube_content_fingerprints", ("pub", "dest")),
    ("youtube_research_items", ("run", "dest")),
    ("youtube_research_runs", ("dest",)),
    ("youtube_comments", ("dest",)),
    ("youtube_channel_dna", ("dest",)),
    ("youtube_dna_suggestions", ("dest",)),
    ("youtube_daily_publish_overrides", ("dest",)),
    ("youtube_performance_snapshots", ("dest",)),
    ("youtube_channel_analytics_daily", ("dest",)),
    ("youtube_video_analytics_daily", ("dest",)),
    # Queue before publications, so no upload row survives its publication.
    ("video_jobs", ("pipeline", "dest", "pub")),
    ("publications", ("pipeline", "dest", "video")),
    # Sources before destinations.
    ("douyin_scan_jobs", ("pipeline", "src")),
    ("oauth_states", ("pipeline", "dest")),
    ("douyin_videos", ("pipeline", "src")),
    ("douyin_sources", ("pipeline", "dest")),
    ("pipeline_sources", ("pipeline",)),
    ("destinations", ("pipeline",)),
    ("pipelines", ("pipeline",)),
)

# Columns that must not reference a purged id afterwards (orphan guard).
REFERENCING_COLUMNS = (
    "pipeline_id",
    "destination_id",
    "publication_id",
    "source_id",
    "douyin_video_id",
    "run_id",
    "job_id",
)


def assert_pipeline_deletable(db: Session, pipeline: Pipeline) -> None:
    """Refuse deletion while uploads are running or their outcome is unknown."""
    job = db.execute(
        select(VideoJob.id, VideoJob.status)
        .where(VideoJob.pipeline_id == pipeline.id)
        .where(VideoJob.status.in_(list(BLOCKING_JOB_STATUSES)))
        .limit(1)
    ).first()
    if job is not None:
        raise PipelineDeleteError(
            "PIPELINE_BUSY",
            (
                f"Pipeline đang có job {job.status} ({job.id}). Chờ job upload/"
                "xử lý xong rồi mới xóa để không mất dữ liệu đối soát."
            ),
            409,
        )
    publication = db.execute(
        select(Publication.id, Publication.status)
        .where(Publication.pipeline_id == pipeline.id)
        .where(Publication.status.in_(list(BLOCKING_PUBLICATION_STATUSES)))
        .limit(1)
    ).first()
    if publication is not None:
        raise PipelineDeleteError(
            "PIPELINE_BUSY",
            (
                f"Publication đang {publication.status} ({publication.id}). "
                "Chờ upload/xử lý xong rồi mới xóa."
            ),
            409,
        )


def _purge(
    db: Session, pipeline: Pipeline, tables: set[str] | None = None
) -> dict[str, int]:
    """Delete all pipeline-scoped rows child-first. Caller commits.

    ``tables`` must be resolved before any DELETE starts: opening an extra
    connection mid-transaction (schema inspection) would roll back the whole
    pending purge on pooled connections that share one DBAPI handle.
    """
    if tables is None:
        tables = _existing_tables(db)
    ids = collect_pipeline_ids(db, pipeline.id)
    counts: dict[str, int] = {}
    for table_name, keys in PURGE_STEPS:
        conditions = [(column, ids.get(key, [])) for key, column in (
            (key, {
                "pipeline": "pipeline_id",
                "dest": "destination_id",
                "src": "source_id",
                "video": "douyin_video_id",
                "pub": "publication_id",
                "job": "job_id",
                "run": "run_id",
            }[key]) for key in keys
        )]
        if table_name == "pipelines":
            conditions = [("id", ids["pipeline"])]
        deleted = _delete_rows(db, table_name, conditions, tables)
        if deleted:
            counts[table_name] = counts.get(table_name, 0) + deleted
    # Upload reconciliation markers live in app_settings (no FK), keyed by the
    # job/publication ids we just removed. Delete only those exact keys.
    keys = [f"youtube_upload_attempt:{job_id}" for job_id in ids["job"]]
    keys += [
        f"youtube_upload_publication:{publication_id}"
        for publication_id in ids["pub"]
    ]
    if keys and "app_settings" in tables:
        result = db.execute(
            delete(AppSetting)
            .where(AppSetting.key.in_(keys))
            .execution_options(synchronize_session=False)
        )
        if result.rowcount:
            counts["app_settings"] = int(result.rowcount)
    return counts


def _assert_no_orphans(
    db: Session, ids: dict[str, list[str]], tables: set[str] | None = None
) -> None:
    """Fail closed if any row still references a deleted id."""
    if tables is None:
        tables = _existing_tables(db)
    owners = {
        "pipeline_id": ids["pipeline"],
        "destination_id": ids["dest"],
        "source_id": ids["src"],
        "douyin_video_id": ids["video"],
        "publication_id": ids["pub"],
        "run_id": ids["run"],
    }
    for table_name, table in Base.metadata.tables.items():
        if table_name in PROTECTED_TABLES or table_name not in tables:
            continue
        for column_name, values in owners.items():
            if not values or column_name not in table.c:
                continue
            remaining = db.execute(
                select(func.count()).select_from(table).where(
                    table.c[column_name].in_(values)
                )
            ).scalar_one_or_none() or 0
            if int(remaining) > 0:
                raise PipelineDeleteError(
                    "PIPELINE_DELETE_INCOMPLETE",
                    (
                        f"Còn {remaining} bản ghi {table_name}.{column_name} "
                        "tham chiếu pipeline sau khi xóa; đã rollback, dữ liệu "
                        "được giữ nguyên."
                    ),
                    409,
                )


def _restore_enabled(
    db: Session, pipeline_id: str, was_enabled: bool, enabled_destination_ids: list[str]
) -> None:
    """Best-effort restore after a failed delete. Never raises."""
    try:
        db.rollback()
        db.execute(
            update(Pipeline)
            .where(Pipeline.id == pipeline_id)
            .values(enabled=was_enabled)
        )
        if enabled_destination_ids:
            db.execute(
                update(Destination)
                .where(Destination.id.in_(enabled_destination_ids))
                .values(enabled=True)
            )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        logger.exception(
            "Could not restore enabled flags after failed pipeline delete %s",
            pipeline_id,
        )


def delete_pipeline(db: Session, pipeline: Pipeline) -> dict[str, Any]:
    """Delete one pipeline and its own rows. Returns deletion counts.

    Raises :class:`PipelineDeleteError` for every failure path; the database is
    left unchanged (or enabled flags restored) when that happens.
    """
    pipeline_id = pipeline.id
    was_enabled = bool(pipeline.enabled)
    enabled_destination_ids = _ids(
        db,
        select(Destination.id).where(
            Destination.pipeline_id == pipeline_id,
            Destination.enabled.is_(True),
        ),
    )

    # Phase 1: stop the scheduler/worker from picking up new work for this
    # pipeline. Committed so other connections observe it before the purge.
    try:
        db.execute(
            update(Pipeline)
            .where(Pipeline.id == pipeline_id)
            .values(enabled=False)
        )
        if enabled_destination_ids:
            db.execute(
                update(Destination)
                .where(Destination.id.in_(enabled_destination_ids))
                .values(enabled=False)
            )
        db.commit()
    except SQLAlchemyError as exc:
        _restore_enabled(db, pipeline_id, was_enabled, enabled_destination_ids)
        raise PipelineDeleteError(
            "PIPELINE_DELETE_FAILED",
            f"Không tạm dừng được pipeline trước khi xóa ({type(exc).__name__}).",
            500,
        ) from exc

    # Phase 2: purge in one transaction; rollback leaves all data intact.
    # Resolve table names before the first DELETE (see _purge docstring).
    tables = _existing_tables(db)
    try:
        assert_pipeline_deletable(db, pipeline)
        ids = collect_pipeline_ids(db, pipeline_id)
        counts = _purge(db, pipeline, tables=tables)
        _assert_no_orphans(db, ids, tables=tables)
        db.commit()
        return counts
    except PipelineDeleteError:
        _restore_enabled(db, pipeline_id, was_enabled, enabled_destination_ids)
        raise
    except SQLAlchemyError as exc:
        _restore_enabled(db, pipeline_id, was_enabled, enabled_destination_ids)
        logger.exception("Pipeline delete failed for %s", pipeline_id)
        raise PipelineDeleteError(
            "PIPELINE_DELETE_CONFLICT",
            (
                "Không xóa được pipeline do ràng buộc dữ liệu "
                f"({type(exc).__name__}); đã rollback, không có dữ liệu nào bị xóa."
            ),
            409,
        ) from exc
    except Exception as exc:
        _restore_enabled(db, pipeline_id, was_enabled, enabled_destination_ids)
        logger.exception("Unexpected pipeline delete failure for %s", pipeline_id)
        raise PipelineDeleteError(
            "PIPELINE_DELETE_FAILED",
            f"Lỗi không xác định khi xóa pipeline ({type(exc).__name__}); đã rollback.",
            500,
        ) from exc


def pipeline_management_counts(db: Session, pipeline_id: str) -> dict[str, int]:
    """Row counts per pipeline-scoped table (tests/diagnostics)."""
    ids = collect_pipeline_ids(db, pipeline_id)
    tables = _existing_tables(db)
    result: dict[str, int] = {}
    for table_name in Base.metadata.tables:
        if table_name in PROTECTED_TABLES or table_name not in tables:
            continue
        table = Base.metadata.tables[table_name]
        clauses = []
        for key, column in (
            ("pipeline", "pipeline_id"),
            ("dest", "destination_id"),
            ("src", "source_id"),
            ("video", "douyin_video_id"),
            ("pub", "publication_id"),
            ("job", "job_id"),
            ("run", "run_id"),
        ):
            if column in table.c and ids.get(key):
                clauses.append(table.c[column].in_(ids[key]))
        if not clauses:
            continue
        result[table_name] = int(
            db.execute(
                select(func.count()).select_from(table).where(or_(*clauses))
            ).scalar_one_or_none()
            or 0
        )
    return result
