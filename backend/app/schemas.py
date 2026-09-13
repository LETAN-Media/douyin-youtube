from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class JobCreate(BaseModel):
    douyin_url: str = Field(
        min_length=10,
        max_length=2000,
    )

    title: str | None = Field(
        default=None,
        max_length=100,
    )

    description: str | None = Field(
        default=None,
        max_length=5000,
    )

    privacy_status: Literal[
        "private",
        "unlisted",
        "public",
    ] = "private"

    @field_validator("douyin_url")
    @classmethod
    def validate_douyin_url(cls, value: str) -> str:
        value = value.strip()
        parsed = urlparse(value)

        if parsed.scheme not in {"http", "https"}:
            raise ValueError("URL phải dùng http hoặc https")

        hostname = (parsed.hostname or "").lower()

        allowed = (
            hostname == "douyin.com"
            or hostname.endswith(".douyin.com")
            or hostname == "iesdouyin.com"
            or hostname.endswith(".iesdouyin.com")
        )

        if not allowed:
            raise ValueError("Chỉ chấp nhận URL Douyin")

        return value


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_url: str
    source_title: str | None

    title: str | None
    description: str | None

    privacy_status: str
    status: str

    attempts: int
    progress: int

    youtube_video_id: str | None
    youtube_url: str | None

    error: str | None

    created_at: datetime
    updated_at: datetime
