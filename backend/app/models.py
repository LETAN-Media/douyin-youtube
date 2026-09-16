import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Pipeline(Base):
    __tablename__ = "pipelines"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    slug: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
    )

    niche: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    language: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
    )

    fixed_hashtags: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    adaptive_hashtags: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    prompt_profile: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    default_privacy: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="public",
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    youtube_credentials: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    youtube_connected: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    youtube_channel_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    youtube_channel_title: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
    )

    sources: Mapped[list["DouyinSource"]] = relationship(
        back_populates="pipeline",
        lazy="selectin",
    )

    videos: Mapped[list["DouyinVideo"]] = relationship(
        back_populates="pipeline",
        lazy="selectin",
    )

    destinations: Mapped[list["Destination"]] = relationship(
        back_populates="pipeline",
        lazy="selectin",
    )

    publications: Mapped[list["Publication"]] = relationship(
        back_populates="pipeline",
        lazy="selectin",
    )

    daily_upload_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=6,
    )

    upload_slots: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
        default=lambda: ["08:00", "11:00", "14:00", "17:00", "20:00", "23:00"],
    )

    backlog_slots_per_day: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=4,
    )

    new_slots_per_day: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=2,
    )

    backlog_order: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="asc",
    )

    source_selection_strategy: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="round_robin",
    )

    source_selection_cursor: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    backlog_threshold_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=7,
    )

    timezone: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="UTC",
    )


class DouyinSource(Base):
    __tablename__ = "douyin_sources"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    pipeline_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("pipelines.id", ondelete="CASCADE"),
        nullable=True,
    )

    destination_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("destinations.id", ondelete="SET NULL"),
        nullable=True,
    )

    pipeline: Mapped["Pipeline | None"] = relationship(
        back_populates="sources",
    )

    videos: Mapped[list["DouyinVideo"]] = relationship(
        back_populates="source",
        lazy="selectin",
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    original_profile_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    profile_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    douyin_sec_uid: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    douyin_user_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    inventory_sync_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="idle",
    )

    inventory_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    inventory_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    inventory_sync_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    last_video_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class DouyinVideo(Base):
    __tablename__ = "douyin_videos"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    source_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("douyin_sources.id", ondelete="SET NULL"),
        nullable=True,
    )

    pipeline_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pipelines.id", ondelete="CASCADE"),
        nullable=False,
    )

    video_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
        default="",
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )

    url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    thumbnail_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    douyin_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="inventory",
        index=True,
    )

    is_backlog: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    is_backfill: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    youtube_video_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    youtube_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    pipeline: Mapped["Pipeline"] = relationship(
        back_populates="videos",
    )

    source: Mapped["DouyinSource | None"] = relationship(
        back_populates="videos",
    )

    publications: Mapped[list["Publication"]] = relationship(
        back_populates="douyin_video",
        lazy="selectin",
    )


class Destination(Base):
    __tablename__ = "destinations"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    pipeline_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pipelines.id", ondelete="CASCADE"),
        nullable=False,
    )

    pipeline: Mapped["Pipeline"] = relationship(
        back_populates="destinations",
    )

    platform: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    external_account_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    external_account_name: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
    )

    credentials: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    connected: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    daily_upload_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=6,
    )

    backlog_slots_per_day: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=4,
    )

    new_slots_per_day: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=2,
    )

    timezone: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="UTC",
    )

    upload_slots: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
        default=lambda: ["08:00", "11:00", "14:00", "17:00", "20:00", "23:00"],
    )

    publish_strategy: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="broadcast",
    )

    metadata_language: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
    )

    metadata_profile: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    fixed_hashtags: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    adaptive_hashtags: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    prompt_override: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    last_scheduler_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_cycle_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_job_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_skip_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    publications: Mapped[list["Publication"]] = relationship(
        back_populates="destination",
        lazy="selectin",
    )


class Publication(Base):
    __tablename__ = "publications"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    pipeline_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pipelines.id", ondelete="CASCADE"),
        nullable=False,
    )

    pipeline: Mapped["Pipeline"] = relationship(
        back_populates="publications",
    )

    douyin_video_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("douyin_videos.id", ondelete="CASCADE"),
        nullable=False,
    )

    douyin_video: Mapped["DouyinVideo"] = relationship(
        back_populates="publications",
    )

    destination_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("destinations.id", ondelete="CASCADE"),
        nullable=False,
    )

    destination: Mapped["Destination"] = relationship(
        back_populates="publications",
    )

    platform: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    publication_mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="auto",
        server_default="auto",
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="queued",
        index=True,
    )

    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    external_post_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    external_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    title: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    jobs: Mapped[list["VideoJob"]] = relationship(
        back_populates="publication",
        foreign_keys="VideoJob.publication_id",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint(
            "douyin_video_id",
            "destination_id",
            name="uq_publication_video_destination",
        ),
    )


class VideoJob(Base):
    __tablename__ = "video_jobs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    source_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    source_title: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    title: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    privacy_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="private",
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
        index=True,
    )

    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    progress: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    youtube_video_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    youtube_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    pipeline_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("pipelines.id", ondelete="SET NULL"),
        nullable=True,
    )

    destination_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("destinations.id", ondelete="SET NULL"),
        nullable=True,
    )

    publication_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("publications.id", ondelete="SET NULL"),
        nullable=True,
    )

    publication: Mapped["Publication | None"] = relationship(
        back_populates="jobs",
        foreign_keys="VideoJob.publication_id",
    )

    source_video_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    schedule_slot_key: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "pipeline_id",
            "schedule_slot_key",
            name="uq_video_job_pipeline_slot",
        ),
    )


class DouyinSession(Base):
    """Saved Douyin web login session (QR login via dashboard).

    The Playwright storage_state JSON is stored Fernet-encrypted and is
    never returned by any API. Login success is only recorded after real
    detection (login cookies + dismissed login modal), never faked.
    """

    __tablename__ = "douyin_sessions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    label: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        default="Douyin",
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
    )

    storage_state_encrypted: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    account_name: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )

    value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class OAuthState(Base):
    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
    )

    pipeline_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("pipelines.id", ondelete="SET NULL"),
        nullable=True,
    )

    destination_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("destinations.id", ondelete="SET NULL"),
        nullable=True,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
