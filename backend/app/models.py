import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

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

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
