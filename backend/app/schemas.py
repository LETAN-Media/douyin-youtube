from datetime import datetime
from typing import Literal
from urllib.parse import urlparse
import re

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PipelineBase(BaseModel):
    name: str = Field(
        max_length=200,
    )
    slug: str = Field(
        max_length=100,
    )
    niche: str | None = Field(
        default=None,
        max_length=500,
    )
    language: str | None = Field(
        default=None,
        max_length=10,
    )
    fixed_hashtags: list[str] | None = Field(
        default=None,
    )
    adaptive_hashtags: list[str] | None = Field(
        default=None,
    )
    prompt_profile: str | None = Field(
        default=None,
    )
    default_privacy: Literal[
        "private",
        "unlisted",
        "public",
    ] = "public"
    enabled: bool = True

    daily_upload_limit: int = 6
    upload_slots: list[str] | None = Field(
        default=["08:00", "11:00", "14:00", "17:00", "20:00", "23:00"],
    )
    backlog_slots_per_day: int = 4
    new_slots_per_day: int = 2
    backlog_order: Literal["asc", "desc"] = "asc"
    source_selection_strategy: Literal["round_robin"] = "round_robin"
    backlog_threshold_days: int = 7
    timezone: str = "UTC"


class PipelineCreate(PipelineBase):
    pass


class PipelineUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        max_length=200,
    )
    slug: str | None = Field(
        default=None,
        max_length=100,
    )
    niche: str | None = Field(
        default=None,
        max_length=500,
    )
    language: str | None = Field(
        default=None,
        max_length=10,
    )
    fixed_hashtags: list[str] | None = Field(
        default=None,
    )
    adaptive_hashtags: list[str] | None = Field(
        default=None,
    )
    prompt_profile: str | None = Field(
        default=None,
    )
    default_privacy: Literal[
        "private",
        "unlisted",
        "public",
    ] | None = Field(
        default=None,
    )
    enabled: bool | None = Field(
        default=None,
    )
    daily_upload_limit: int | None = Field(
        default=None,
        ge=1,
    )
    upload_slots: list[str] | None = Field(
        default=None,
    )
    backlog_slots_per_day: int | None = Field(
        default=None,
        ge=0,
    )
    new_slots_per_day: int | None = Field(
        default=None,
        ge=0,
    )
    backlog_order: Literal["asc", "desc"] | None = Field(
        default=None,
    )
    source_selection_strategy: Literal["round_robin"] | None = Field(
        default=None,
    )
    backlog_threshold_days: int | None = Field(
        default=None,
        ge=1,
    )
    timezone: str | None = Field(
        default=None,
        max_length=50,
    )


class PipelineOut(PipelineBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class DouyinSourceBase(BaseModel):
    name: str = Field(
        max_length=200,
    )
    profile_url: str | None = Field(
        default=None,
        max_length=2000,
    )
    douyin_sec_uid: str | None = Field(
        default=None,
        max_length=200,
    )
    douyin_user_id: str | None = Field(
        default=None,
        max_length=200,
    )
    enabled: bool = True


class DouyinSourceCreate(DouyinSourceBase):
    pipeline_id: str | None = Field(
        default=None,
        max_length=36,
    )


class DouyinSourceUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        max_length=200,
    )
    profile_url: str | None = Field(
        default=None,
        max_length=2000,
    )
    douyin_sec_uid: str | None = Field(
        default=None,
        max_length=200,
    )
    douyin_user_id: str | None = Field(
        default=None,
        max_length=200,
    )
    enabled: bool | None = Field(
        default=None,
    )
    last_video_id: str | None = Field(
        default=None,
        max_length=200,
    )
    last_checked_at: datetime | None = Field(
        default=None,
    )


class DouyinSourceOut(DouyinSourceBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    pipeline_id: str | None
    original_profile_url: str | None
    profile_url: str | None
    douyin_sec_uid: str | None
    douyin_user_id: str | None
    inventory_sync_status: str
    last_video_id: str | None
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class JobCreate(BaseModel):
    pipeline_id: str | None = Field(
        default=None,
        max_length=36,
    )

    douyin_url: str | None = Field(
        default=None,
        max_length=2000,
    )

    share_text: str | None = Field(
        default=None,
        max_length=10000,
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
    ] = "public"

    @model_validator(mode="before")
    @classmethod
    def validate_inputs(cls, data: dict) -> dict:
        douyin_url = data.get("douyin_url")
        share_text = data.get("share_text")

        if not douyin_url and share_text:
            match = re.search(r'https?://v\.douyin\.com/[a-zA-Z0-9]+/?', share_text)
            if match:
                douyin_url = match.group(0)
                data["douyin_url"] = douyin_url

        if not douyin_url:
            raise ValueError("Thiếu douyin_url hoặc share_text không chứa URL hợp lệ.")
            
        douyin_url = douyin_url.strip()
        parsed = urlparse(douyin_url)

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

        data["douyin_url"] = douyin_url
        return data


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

    pipeline_id: str | None

    source_video_id: str | None

    destination_id: str | None

    created_at: datetime
    updated_at: datetime


class DestinationBase(BaseModel):
    pipeline_id: str = Field(
        max_length=36,
    )
    platform: Literal["youtube", "facebook"] = "youtube"
    name: str = Field(
        max_length=200,
    )
    external_account_id: str | None = Field(
        default=None,
        max_length=200,
    )
    external_account_name: str | None = Field(
        default=None,
        max_length=300,
    )
    enabled: bool = True
    daily_upload_limit: int = 6
    timezone: str = "UTC"
    upload_slots: list[str] | None = Field(
        default=["08:00", "11:00", "14:00", "17:00", "20:00", "23:00"],
    )
    publish_strategy: Literal["broadcast", "rotate", "selected"] = "broadcast"
    metadata_language: str | None = Field(
        default=None,
        max_length=10,
    )
    metadata_profile: str | None = Field(
        default=None,
    )
    fixed_hashtags: list[str] | None = Field(
        default=None,
    )
    adaptive_hashtags: list[str] | None = Field(
        default=None,
    )
    prompt_override: str | None = Field(
        default=None,
    )


class DestinationCreate(DestinationBase):
    pass


class DestinationUpdate(BaseModel):
    platform: Literal["youtube", "facebook"] | None = Field(
        default=None,
    )
    name: str | None = Field(
        default=None,
        max_length=200,
    )
    external_account_id: str | None = Field(
        default=None,
        max_length=200,
    )
    external_account_name: str | None = Field(
        default=None,
        max_length=300,
    )
    enabled: bool | None = Field(
        default=None,
    )
    daily_upload_limit: int | None = Field(
        default=None,
        ge=1,
    )
    timezone: str | None = Field(
        default=None,
        max_length=50,
    )
    upload_slots: list[str] | None = Field(
        default=None,
    )
    publish_strategy: Literal["broadcast", "rotate", "selected"] | None = Field(
        default=None,
    )
    metadata_language: str | None = Field(
        default=None,
        max_length=10,
    )
    metadata_profile: str | None = Field(
        default=None,
    )
    fixed_hashtags: list[str] | None = Field(
        default=None,
    )
    adaptive_hashtags: list[str] | None = Field(
        default=None,
    )
    prompt_override: str | None = Field(
        default=None,
    )


class DestinationOut(DestinationBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    connected: bool
    created_at: datetime
    updated_at: datetime


class PublicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    pipeline_id: str
    douyin_video_id: str
    destination_id: str
    platform: str
    status: str
    scheduled_at: datetime | None
    started_at: datetime | None
    published_at: datetime | None
    external_post_id: str | None
    external_url: str | None
    title: str | None
    description: str | None
    attempts: int
    error: str | None
    created_at: datetime
    updated_at: datetime
