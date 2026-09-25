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


class PlatformAccount(Base):
    """Global platform login shared across all pipelines/sources."""

    __tablename__ = "platform_accounts"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    platform: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        unique=True,
    )

    display_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="needs_login",
    )

    credentials_encrypted: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    needs_reauth: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_error: Mapped[str | None] = mapped_column(
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


# Generic pipeline source (Douyin, Facebook, ...). Implemented via
# douyin_sources table for backwards compat; platform field makes it generic.
# New code should use PipelineSource alias; old code using DouyinSource keeps working.
class PipelineSource(Base):
    __tablename__ = "pipeline_sources"

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

    platform: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="douyin",
    )

    source_external_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    source_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    source_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    avatar_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    last_scan_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_seen_content_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    next_scan_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_error: Mapped[str | None] = mapped_column(
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

    # Generic platform support (douyin/facebook). Default douyin for legacy rows.
    platform: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="douyin",
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

    # ---- AUTO mode: per-source cookie + scan policy ----
    # Cookie is stored Fernet-encrypted, never plaintext, never logged.
    cookie_encrypted: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    cookie_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="missing",
    )

    cookie_account_name: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
    )

    cookie_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    needs_reauth: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    scan_interval_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=15,
    )

    max_videos_per_day: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=50,
    )

    include_keywords: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    exclude_keywords: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    next_scan_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_scan_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # NEW_ONLY (default): first sync only establishes a baseline, uploads
    # nothing historical. LAST_N: keep newest N videos as active inventory.
    start_mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="new_only",
    )

    initial_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=10,
    )

    baseline_done: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    # AI verdict policies for AUTO inventory.
    borderline_policy: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="hold",
    )

    mismatch_policy: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="reject",
    )

    order: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="oldest_first",
    )

    # ---- admin-driven Douyin discovery (no scheduled scanning) ----
    # Which creator-feed provider this source uses. Recorded per source so the
    # UI can show it even after the default provider changes.
    feed_provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="rapidapi_justone",
    )

    # Initial full import (one-off backlog walk). Resumable: a quota stop keeps
    # the cursor so the next run continues instead of refetching page 1.
    # pending | running | paused_quota | completed | failed
    initial_import_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
    )

    initial_import_cursor: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    initial_import_pages: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    initial_import_videos: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    initial_import_last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    initial_import_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    initial_import_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Manual "check for new videos" refresh.
    last_refresh_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ok | quota_exhausted | provider_error | invalid
    # Never "needs_login": this provider needs no Douyin cookie at all.
    provider_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="ok",
    )

    provider_status_detail: Mapped[str | None] = mapped_column(
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

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "video_id",
            name="uq_douyin_video_source_video",
        ),
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

    # Minimum minutes between two YouTube uploads for this destination.
    min_upload_interval_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    publications: Mapped[list["Publication"]] = relationship(
        back_populates="destination",
        lazy="selectin",
    )

    # ---- AI Comment Reply -------------------------------------------------
    # Deliberately SEPARATE from the metadata fields above: prompt_override /
    # metadata_profile / metadata_language only ever feed title/description/
    # hashtags, while the comment_* fields below only ever feed comment
    # analysis and replies. The two prompt sets are never merged or reused.
    comment_reply_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    # off | review | auto
    comment_reply_mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="off",
    )

    # The ONLY system prompt used by the comment-reply AI flow.
    comment_reply_system_prompt: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # auto | en | vi | zh ...
    comment_reply_language: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="auto",
    )

    # friendly | funny | warm | short | professional | custom
    comment_reply_style: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="friendly",
    )

    comment_reply_daily_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=20,
    )

    comment_reply_min_interval_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=180,
    )

    comment_reply_new_only: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    # Comment filter config (editable from the dashboard).
    comment_reply_to_positive: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    comment_reply_to_questions: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    comment_reply_to_neutral: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    comment_reply_to_negative: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    comment_reply_to_emoji_only: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    last_comment_scan_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class YouTubeComment(Base):
    """A comment fetched from a channel's own published videos.

    One row per (destination, YouTube comment). Never written by the metadata
    or publishing flows; only the comment worker and the comment routes touch
    it.
    """

    __tablename__ = "youtube_comments"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    destination_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("destinations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # YouTube video id the comment lives on.
    video_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    video_title: Mapped[str | None] = mapped_column(
        String(400),
        nullable=True,
    )

    youtube_comment_id: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        index=True,
    )

    # Set only for replies (commentThreads children).
    parent_comment_id: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    author_channel_id: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    author_name: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
    )

    # Canonical comment text. `comment_text` mirrors it for fetch/dedupe.
    text_original: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )

    comment_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    like_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    # new | analyzing | queued | generated | ready_to_reply | held | ignored
    # | skipped | replying | replied | failed
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="new",
        index=True,
    )

    # Mirror of `status` kept for the fetch/dedupe contract.
    reply_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="new",
    )

    ai_classification: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    ai_reply: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Final reply text that was (or will be) posted.
    reply_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    ai_confidence: Mapped[float | None] = mapped_column(
        nullable=True,
    )

    ai_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Coarse language detected on the comment (en/vi/zh/...).
    detected_language: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    replied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    youtube_reply_id: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
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

    __table_args__ = (
        UniqueConstraint(
            "destination_id",
            "youtube_comment_id",
            name="uq_youtube_comment_destination_comment",
        ),
        UniqueConstraint(
            "youtube_comment_id",
            name="uq_youtube_comment_id",
        ),
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
