from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class BaseDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PipelineCreate(BaseDTO):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    timezone: str = "Asia/Ho_Chi_Minh"
    ordering: str = "newest"
    max_daily_publish: int = 5
    publish_slots: Optional[list[str]] = None
    slot_window_minutes: int = 60
    slot_max_daily: int = 5
    min_interval_minutes: int = 60
    auto_scan: bool = True
    auto_publish: bool = True
    youtube_channel_id: Optional[str] = None
    ai_strategy: str = "auto"
    ai_model: Optional[str] = None
    default_publish_mode: str = "reels_or_video"
    default_facebook_page_id: Optional[str] = None
    settings: Optional[dict] = None


class PipelineUpdate(BaseDTO):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    ordering: Optional[str] = None
    max_daily_publish: Optional[int] = None
    timezone: Optional[str] = None
    publish_slots: Optional[list[str]] = None
    slot_window_minutes: Optional[int] = None
    slot_max_daily: Optional[int] = None
    min_interval_minutes: Optional[int] = None
    auto_scan: Optional[bool] = None
    auto_publish: Optional[bool] = None
    next_scan_at: Optional[datetime] = None
    youtube_channel_id: Optional[str] = None
    ai_strategy: Optional[str] = None
    ai_model: Optional[str] = None
    ai_max_tokens: Optional[int] = None
    ai_temperature: Optional[float] = None
    default_publish_mode: Optional[str] = None
    default_facebook_page_id: Optional[str] = None


class PipelineRead(BaseDTO):
    id: str
    name: str
    description: Optional[str] = None
    status: str
    ordering: str
    max_daily_publish: int
    timezone: str
    publish_slots: list[str]
    slot_window_minutes: int
    slot_max_daily: int
    min_interval_minutes: int
    auto_scan: bool
    auto_publish: bool
    next_scan_at: Optional[datetime] = None
    youtube_channel_id: Optional[str] = None
    youtube_channel_title: Optional[str] = None
    ai_strategy: str
    ai_model: Optional[str] = None
    default_publish_mode: str
    default_facebook_page_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    video_count: Optional[int] = None


class SourceCreate(BaseDTO):
    source_type: str = "channel"
    channel_id: Optional[str] = None
    channel_title: Optional[str] = None
    playlist_id: Optional[str] = None
    custom_url: Optional[str] = None


class SourceRead(BaseDTO):
    id: str
    pipeline_id: str
    source_type: str
    channel_id: Optional[str] = None
    channel_title: Optional[str] = None
    playlist_id: Optional[str] = None
    custom_url: Optional[str] = None
    status: str
    last_scan_at: Optional[datetime] = None
    last_scan_error: Optional[str] = None
    created_at: datetime


class FacebookPageCreate(BaseDTO):
    page_id: str = Field(..., min_length=1)
    page_name: Optional[str] = None
    page_access_token: Optional[str] = None
    scopes: Optional[list[str]] = None
    is_default: bool = False


class FacebookPageRead(BaseDTO):
    id: str
    pipeline_id: str
    page_id: str
    page_name: Optional[str] = None
    scopes: Optional[list[str]] = None
    is_default: bool
    status: str
    error: Optional[str] = None
    synced_at: Optional[datetime] = None
    created_at: datetime


class VideoRead(BaseDTO):
    pipeline_id: str
    video_id: str
    channel_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    duration_seconds: Optional[int] = None
    publish_time: Optional[datetime] = None
    thumbnail_url: Optional[str] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    created_at: datetime


class QueueItemRead(BaseDTO):
    id: str
    pipeline_id: str
    youtube_video_id: str
    facebook_page_id: str
    media_file_id: str
    schedule_id: Optional[str] = None
    status: str
    priority: int
    scheduled_for: Optional[datetime] = None
    retry_count: int
    publish_mode: str
    ai_caption: Optional[str] = None
    ai_enhanced: bool
    title: Optional[str] = None
    description: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime


class ScheduleRead(BaseDTO):
    id: str
    pipeline_id: str
    scheduled_date: str
    slot_index: int
    slot_time: str
    slot_max_daily: int
    publish_count: int
    reserved_count: int
    is_active: bool
    created_at: datetime


class PublicationRead(BaseDTO):
    id: str
    pipeline_id: str
    youtube_video_id: str
    facebook_page_id: str
    media_file_id: Optional[str] = None
    facebook_post_id: Optional[str] = None
    facebook_video_id: Optional[str] = None
    facebook_reel_id: Optional[str] = None
    publish_mode: str
    status: str
    ai_caption: Optional[str] = None
    ai_enhanced: bool
    title: Optional[str] = None
    description: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: datetime


class ManualPublishRequest(BaseDTO):
    youtube_url: str = Field(..., min_length=1)
    facebook_page_id: str = Field(..., min_length=1)
    publish_mode: str = "reels_or_video"
    caption: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    schedule_for: Optional[datetime] = None
    use_ai_caption: bool = True


class ScanRequest(BaseDTO):
    source_ids: Optional[list[str]] = None
    full_rescan: bool = False
