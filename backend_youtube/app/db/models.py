from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .base import Base


def _ts_column() -> DateTime:
    return DateTime(timezone=True)


class PipelineStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    DRAFT = "draft"


class PipelineOrdering(str, Enum):
    NEWEST = "newest"
    OLDEST = "oldest"


class SourceStatus(str, Enum):
    ENABLED = "enabled"
    PAUSED = "paused"
    ERROR = "error"


class QueueStatus(str, Enum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(str, Enum):
    YOUTUBE_SCAN = "youtube_scan"
    MEDIA_ACQUIRE = "media_acquire"
    AI_CAPTION = "ai_caption"
    PUBLISH = "publish"
    FACEBOOK_LIVE = "facebook_live"


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PublishMode(str, Enum):
    REELS = "reels"
    VIDEO = "video"
    REELS_OR_VIDEO = "reels_or_video"


class FacebookPageStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"


class AIStrategy(str, Enum):
    OFF = "off"
    AUTO = "auto"
    ENHANCE = "enhance"


class PublicationOutcome(str, Enum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


class MediaStatus(str, Enum):
    PENDING = "pending"
    ACQUIRING = "acquiring"
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"


class MediaPublishStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    PUBLISHED = "published"
    SKIPPED = "skipped"


class Pipeline(Base):
    __tablename__ = "pipelines"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, comment="youtube_{hex}")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=PipelineStatus.ACTIVE)
    ordering: Mapped[str] = mapped_column(String(20), nullable=False, default=PipelineOrdering.NEWEST)
    max_daily_publish: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Ho_Chi_Minh")
    publish_slots: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    slot_window_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    slot_max_daily: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    min_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    auto_scan: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auto_publish: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_scan_at: Mapped[DateTime | None] = mapped_column(_ts_column(), nullable=True)
    youtube_channel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    youtube_channel_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ai_strategy: Mapped[str] = mapped_column(String(20), nullable=False, default=AIStrategy.AUTO)
    ai_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ai_max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    ai_temperature: Mapped[float] = mapped_column(SmallInteger, nullable=False, default=70)
    ai_max_requests_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    ai_max_tokens_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=8000)
    default_publish_mode: Mapped[str] = mapped_column(String(20), nullable=False, default=PublishMode.REELS_OR_VIDEO)
    default_facebook_page_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(_ts_column(), nullable=False, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(_ts_column(), nullable=False, server_default=func.now(), onupdate=func.now())
    settings: Mapped[dict] = mapped_column(JSON, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, nullable=True)

    sources: Mapped[list["YouTubeSource"]] = relationship(back_populates="pipeline", cascade="all, delete-orphan")
    facebook_pages: Mapped[list["FacebookPage"]] = relationship(back_populates="pipeline", cascade="all, delete-orphan")
    schedules: Mapped[list["PublishSchedule"]] = relationship(back_populates="pipeline", cascade="all, delete-orphan")
    videos: Mapped[list["YouTubeVideo"]] = relationship(back_populates="pipeline", cascade="all, delete-orphan")
    queue_items: Mapped[list["PublishQueue"]] = relationship(back_populates="pipeline", cascade="all, delete-orphan")
    publications: Mapped[list["PublicationHistory"]] = relationship(back_populates="pipeline", cascade="all, delete-orphan")
    ai_metadata: Mapped[list["AIMetadata"]] = relationship(back_populates="pipeline", cascade="all, delete-orphan")
    jobs: Mapped[list["BackgroundJob"]] = relationship(back_populates="pipeline", cascade="all, delete-orphan")
    publication_attempts: Mapped[list["PublicationAttempt"]] = relationship(back_populates="pipeline", cascade="all, delete-orphan")


class YouTubeSource(Base):
    __tablename__ = "youtube_sources"
    __table_args__ = (
        Index("ix_youtube_sources_pipeline_id_type", "pipeline_id", "source_type"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="yt_{hex}")
    pipeline_id: Mapped[str] = mapped_column(ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="channel")
    channel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    channel_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    playlist_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    custom_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=SourceStatus.ENABLED)
    last_scan_at: Mapped[DateTime | None] = mapped_column(_ts_column(), nullable=True)
    last_scan_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(_ts_column(), nullable=False, server_default=func.now())

    pipeline: Mapped["Pipeline"] = relationship(back_populates="sources")


class YouTubeVideo(Base):
    __tablename__ = "youtube_videos"
    __table_args__ = (
        Index("ix_youtube_videos_pipeline_id", "pipeline_id"),
        Index("ix_youtube_videos_channel_id", "channel_id"),
    )

    pipeline_id: Mapped[str] = mapped_column(ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False)
    video_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    channel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    publish_time: Mapped[DateTime | None] = mapped_column(_ts_column(), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    view_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    like_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(_ts_column(), nullable=False, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(_ts_column(), nullable=False, server_default=func.now(), onupdate=func.now())

    pipeline: Mapped["Pipeline"] = relationship(back_populates="videos")


class MediaFile(Base):
    __tablename__ = "media_files"
    __table_args__ = (
        Index("ix_media_files_pipeline_id_video_id", "pipeline_id", "youtube_video_id"),
        Index("ix_media_files_status", "pipeline_id", "publish_status"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True, comment="media_{hex}")
    pipeline_id: Mapped[str] = mapped_column(ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False)
    youtube_video_id: Mapped[str] = mapped_column(ForeignKey("youtube_videos.video_id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=MediaStatus.PENDING)
    resolution: Mapped[str | None] = mapped_column(String(32), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    remote_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    download_started_at: Mapped[DateTime | None] = mapped_column(_ts_column(), nullable=True)
    download_completed_at: Mapped[DateTime | None] = mapped_column(_ts_column(), nullable=True)
    processing_started_at: Mapped[DateTime | None] = mapped_column(_ts_column(), nullable=True)
    processing_completed_at: Mapped[DateTime | None] = mapped_column(_ts_column(), nullable=True)
    publish_status: Mapped[str] = mapped_column(String(20), nullable=False, default=MediaPublishStatus.PENDING)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(_ts_column(), nullable=False, server_default=func.now())

    pipeline: Mapped["Pipeline"] = relationship()
    queue_items: Mapped[list["PublishQueue"]] = relationship(back_populates="media_file")


class FacebookPage(Base):
    __tablename__ = "facebook_pages"
    __table_args__ = (
        Index("ix_facebook_pages_pipeline_id_default", "pipeline_id", "is_default"),
        UniqueConstraint("pipeline_id", "page_id", name="uq_facebook_pages_pipeline_page"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="page_{hex}")
    pipeline_id: Mapped[str] = mapped_column(ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False)
    page_id: Mapped[str] = mapped_column(String(64), nullable=False)
    page_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    page_access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=True)
    page_access_token_expires_at: Mapped[DateTime | None] = mapped_column(_ts_column(), nullable=True)
    scopes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=FacebookPageStatus.ENABLED)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[DateTime | None] = mapped_column(_ts_column(), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(_ts_column(), nullable=False, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(_ts_column(), nullable=False, server_default=func.now(), onupdate=func.now())

    pipeline: Mapped["Pipeline"] = relationship(back_populates="facebook_pages")
    queue_items: Mapped[list["PublishQueue"]] = relationship(back_populates="facebook_page")


class PublishSchedule(Base):
    __tablename__ = "publish_schedules"
    __table_args__ = (
        Index("ix_publish_schedules_pipeline_date", "pipeline_id", "scheduled_date"),
        UniqueConstraint("pipeline_id", "scheduled_date", "slot_index", name="uq_publish_schedules_slot"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True, comment="sched_{hex}")
    pipeline_id: Mapped[str] = mapped_column(ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False)
    scheduled_date: Mapped[str] = mapped_column(String(10), nullable=False)
    slot_index: Mapped[int] = mapped_column(Integer, nullable=False)
    slot_time: Mapped[str] = mapped_column(String(5), nullable=False)
    slot_max_daily: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    publish_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[DateTime] = mapped_column(_ts_column(), nullable=False, server_default=func.now())

    pipeline: Mapped["Pipeline"] = relationship(back_populates="schedules")


class PublishQueue(Base):
    __tablename__ = "publish_queue"
    __table_args__ = (
        Index("ix_publish_queue_status_pipeline", "pipeline_id", "status"),
        Index("ix_publish_queue_scheduled_for", "scheduled_for"),
        Index("ix_publish_queue_reservation", "reservation_token"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True, comment="pq_{hex}")
    pipeline_id: Mapped[str] = mapped_column(ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False)
    youtube_video_id: Mapped[str] = mapped_column(ForeignKey("youtube_videos.video_id", ondelete="CASCADE"), nullable=False)
    facebook_page_id: Mapped[str] = mapped_column(ForeignKey("facebook_pages.id", ondelete="CASCADE"), nullable=False)
    media_file_id: Mapped[str] = mapped_column(ForeignKey("media_files.id", ondelete="CASCADE"), nullable=False)
    schedule_id: Mapped[str | None] = mapped_column(ForeignKey("publish_schedules.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=QueueStatus.PENDING)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scheduled_for: Mapped[DateTime | None] = mapped_column(_ts_column(), nullable=True)
    reservation_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reservation_expires_at: Mapped[DateTime | None] = mapped_column(_ts_column(), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    publish_mode: Mapped[str] = mapped_column(String(20), nullable=False, default=PublishMode.REELS_OR_VIDEO)
    ai_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_enhanced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[DateTime | None] = mapped_column(_ts_column(), nullable=True)
    completed_at: Mapped[DateTime | None] = mapped_column(_ts_column(), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(_ts_column(), nullable=False, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(_ts_column(), nullable=False, server_default=func.now(), onupdate=func.now())

    pipeline: Mapped["Pipeline"] = relationship(back_populates="queue_items")
    media_file: Mapped["MediaFile"] = relationship(back_populates="queue_items")
    facebook_page: Mapped["FacebookPage"] = relationship(back_populates="queue_items")


class PublicationHistory(Base):
    __tablename__ = "publication_history"
    __table_args__ = (
        Index("ix_publication_history_pipeline_video_page", "pipeline_id", "youtube_video_id", "facebook_page_id"),
        UniqueConstraint("pipeline_id", "youtube_video_id", "facebook_page_id", name="uq_publication_history_unique_pub"),
        Index("ix_publication_history_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True, comment="pub_{hex}")
    pipeline_id: Mapped[str] = mapped_column(ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False)
    youtube_video_id: Mapped[str] = mapped_column(String(64), nullable=False)
    facebook_page_id: Mapped[str] = mapped_column(String(64), nullable=False)
    media_file_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    facebook_post_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    facebook_video_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    facebook_reel_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    publish_mode: Mapped[str] = mapped_column(String(20), nullable=False, default=PublishMode.REELS_OR_VIDEO)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=PublicationOutcome.SUCCESS)
    ai_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_enhanced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    published_at: Mapped[DateTime | None] = mapped_column(_ts_column(), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(_ts_column(), nullable=False, server_default=func.now())

    pipeline: Mapped["Pipeline"] = relationship(back_populates="publications")


class AIMetadata(Base):
    __tablename__ = "ai_metadata"
    __table_args__ = (
        UniqueConstraint("pipeline_id", "youtube_video_id", name="uq_ai_metadata_pipeline_video"),
        Index("ix_ai_metadata_pipeline_video", "pipeline_id", "youtube_video_id"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True, comment="ai_{hex}")
    pipeline_id: Mapped[str] = mapped_column(ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False)
    youtube_video_id: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy: Mapped[str] = mapped_column(String(20), nullable=False, default=AIStrategy.AUTO)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enhanced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    hashtags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    title_suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(_ts_column(), nullable=False, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(_ts_column(), nullable=False, server_default=func.now(), onupdate=func.now())

    pipeline: Mapped["Pipeline"] = relationship(back_populates="ai_metadata")


class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        Index("ix_background_jobs_pipeline_type_status", "pipeline_id", "job_type", "status"),
        Index("ix_background_jobs_scheduled_for", "scheduled_for"),
        Index("ix_background_jobs_reservation", "reservation_token"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True, comment="job_{hex}")
    pipeline_id: Mapped[str] = mapped_column(ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=JobStatus.PENDING)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scheduled_for: Mapped[DateTime | None] = mapped_column(_ts_column(), nullable=True)
    reservation_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reservation_expires_at: Mapped[DateTime | None] = mapped_column(_ts_column(), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(_ts_column(), nullable=False, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(_ts_column(), nullable=False, server_default=func.now(), onupdate=func.now())

    pipeline: Mapped["Pipeline"] = relationship(back_populates="jobs")


class PublicationAttempt(Base):
    __tablename__ = "publication_attempts"
    __table_args__ = (
        Index("ix_publication_attempts_queue_id", "queue_item_id"),
        Index("ix_publication_attempts_pipeline", "pipeline_id"),
        Index("ix_publication_attempts_attempt", "queue_item_id", "attempt_number"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True, comment="pa_{hex}")
    pipeline_id: Mapped[str] = mapped_column(ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False)
    queue_item_id: Mapped[str] = mapped_column(ForeignKey("publish_queue.id", ondelete="CASCADE"), nullable=False)
    facebook_page_id: Mapped[str] = mapped_column(ForeignKey("facebook_pages.id", ondelete="CASCADE"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    publish_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    facebook_post_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    facebook_reel_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    facebook_video_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[DateTime] = mapped_column(_ts_column(), nullable=False, server_default=func.now())
    completed_at: Mapped[DateTime | None] = mapped_column(_ts_column(), nullable=True)

    pipeline: Mapped["Pipeline"] = relationship(back_populates="publication_attempts")


class QuotaState(Base):
    __tablename__ = "quota_state"

    pipeline_id: Mapped[str] = mapped_column(ForeignKey("pipelines.id", ondelete="CASCADE"), primary_key=True)
    date: Mapped[str] = mapped_column(String(10), primary_key=True)
    published_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quota_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    reset_at: Mapped[DateTime] = mapped_column(_ts_column(), nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(_ts_column(), nullable=False, server_default=func.now(), onupdate=func.now())

    pipeline: Mapped["Pipeline"] = relationship()
