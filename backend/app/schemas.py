from datetime import datetime
from typing import Any, Literal
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
    scan_interval_minutes: int | None = Field(default=None, ge=5, le=1440)
    max_videos_per_day: int | None = Field(default=None, ge=0, le=50)
    include_keywords: list[str] | None = None
    exclude_keywords: list[str] | None = None
    start_mode: Literal["new_only", "last_n"] | None = None
    initial_limit: int | None = Field(default=None, ge=1, le=50)
    borderline_policy: Literal["hold", "continue"] | None = None
    mismatch_policy: Literal["reject", "hold"] | None = None
    order: Literal["oldest_first", "newest_first"] | None = None
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
    inventory_count: int = 0
    inventory_synced_at: datetime | None = None
    inventory_sync_error: str | None = None
    last_video_id: str | None
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # AUTO mode fields (plain columns; cookie value never exposed)
    cookie_status: str = "missing"
    cookie_account_name: str | None = None
    cookie_verified_at: datetime | None = None
    needs_reauth: bool = False
    scan_interval_minutes: int = 15
    max_videos_per_day: int = 5
    include_keywords: list[str] | None = None
    exclude_keywords: list[str] | None = None
    next_scan_at: datetime | None = None
    last_scan_at: datetime | None = None
    start_mode: str = "new_only"
    initial_limit: int = 10
    baseline_done: bool = False
    borderline_policy: str = "hold"
    mismatch_policy: str = "reject"
    order: str = "oldest_first"


class SourceWithCookieOut(DouyinSourceOut):
    """Source detail incl. public cookie state (never the cookie itself)."""

    cookie_configured: bool = False


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

    publication_id: str | None = None

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


class DestinationCreate(BaseModel):
    pipeline_id: str | None = Field(
        default=None,
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
    daily_upload_limit: int = Field(default=6, ge=1, le=50)
    timezone: str = Field(default="UTC", max_length=50)
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
    last_scheduler_check_at: datetime | None = None
    last_cycle_at: datetime | None = None
    last_job_created_at: datetime | None = None
    last_skip_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class PublicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    pipeline_id: str
    douyin_video_id: str
    destination_id: str
    platform: str
    publication_mode: str = "auto"
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


class DouyinVideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str | None = None
    pipeline_id: str
    video_id: str
    title: str
    description: str
    url: str
    thumbnail_url: str | None = None
    douyin_created_at: datetime | None
    status: str
    is_backlog: bool
    is_backfill: bool = False
    scheduled_at: datetime | None
    published_at: datetime | None
    youtube_video_id: str | None
    youtube_url: str | None
    created_at: datetime
    updated_at: datetime


class ManualResolveRequest(BaseModel):
    input: str = Field(min_length=1)


class ManualResolveResponse(BaseModel):
    type: Literal["video", "profile"]
    source_url: str
    video_id: str | None = None
    author: str | None = None
    caption: str | None = None
    thumbnail: str | None = None
    duration: int | None = None
    status: str = "Video detected"
    message: str | None = None
    profile_url: str | None = None
    sec_uid: str | None = None


class ManualMetadataItem(BaseModel):
    title: str
    description: str
    hashtags: list[str] = Field(default_factory=list)
    final_description: str
    content_match: bool | None = None
    content_match_reason: str | None = None
    match_level: Literal["match", "borderline", "mismatch"] | None = None


class ManualMetadataRequest(BaseModel):
    source_url: str
    caption: str | None = None
    destination_ids: list[str] = Field(default_factory=list)
    metadata_mode: Literal["same", "separate"] = "same"


class ManualMetadataResponse(BaseModel):
    metadata_mode: str = "same"
    same: ManualMetadataItem | None = None
    by_destination: dict[str, ManualMetadataItem] = Field(default_factory=dict)


class ManualDestinationMetadataInput(BaseModel):
    title: str
    description: str


class ManualPublishRequest(BaseModel):
    source_url: str
    source_title: str | None = None
    video_id: str | None = None
    thumbnail: str | None = None
    duration: int | None = None
    destination_ids: list[str] = Field(min_length=1)
    metadata_mode: Literal["same", "separate"] = "same"
    title: str | None = None
    description: str | None = None
    destinations_metadata: dict[str, ManualDestinationMetadataInput] = Field(default_factory=dict)
    privacy_status: Literal["public", "unlisted", "private"] = "public"
    force_duplicate: bool = False


class ManualPublicationItem(BaseModel):
    id: str
    destination_id: str
    destination_name: str
    platform: str
    status: str
    progress: int = 0
    video_title: str | None = None
    source_url: str | None = None
    thumbnail: str | None = None
    external_url: str | None = None
    error: str | None = None
    created_at: datetime
    published_at: datetime | None = None


class ManualPublishResponse(BaseModel):
    accepted: bool = True
    publications: list[ManualPublicationItem]


class DouyinVideoWithPublications(DouyinVideoOut):
    source_name: str | None = None
    publications: list[PublicationOut] = Field(default_factory=list)


class InventoryListResponse(BaseModel):
    items: list[DouyinVideoOut]
    total: int
    page: int
    page_size: int


class PublicationRescheduleRequest(BaseModel):
    scheduled_at: datetime


class PublicationPublishRequest(BaseModel):
    destination_id: str = Field(max_length=36)


class SourceSyncResponse(BaseModel):
    source_id: str
    status: str
    new: int = 0
    updated: int = 0


class ChannelItem(BaseModel):
    id: str
    destination_id: str
    pipeline_id: str
    pipeline_name: str
    channel_id: str | None = None
    channel_title: str
    avatar_url: str | None = None
    connected: bool
    enabled: bool
    published_today: int = 0
    queue_count: int = 0
    last_published_at: datetime | None = None


class ChannelDetailResponse(BaseModel):
    channel: ChannelItem
    daily_upload_limit: int = 6
    metadata_profile: str | None = None
    metadata_language: str | None = None
    fixed_hashtags: list[str] | None = None
    adaptive_hashtags: list[str] | None = None
    prompt_override: str | None = None
    timezone: str = "UTC"
    pipeline: dict[str, Any]
    sources: list[dict[str, Any]] = Field(default_factory=list)
    queue: list[ManualPublicationItem] = Field(default_factory=list)
    published: list[ManualPublicationItem] = Field(default_factory=list)
    inventory: list[dict[str, Any]] = Field(default_factory=list)
    inventory_count: int = 0
    failed_count: int = 0
    next_slot: str | None = None


class ChannelUpdateRequest(BaseModel):
    name: str | None = None
    daily_upload_limit: int | None = None
    metadata_profile: str | None = None
    metadata_language: str | None = None
    fixed_hashtags: list[str] | None = None
    adaptive_hashtags: list[str] | None = None
    prompt_override: str | None = None
    timezone: str | None = None
    upload_slots: list[str] | None = None
    enabled: bool | None = None
    default_privacy: str | None = None


class ChannelAddSourceRequest(BaseModel):
    name: str
    url: str
    platform: Literal["douyin", "facebook"] = "douyin"
    scan_interval_minutes: int = Field(default=15, ge=5, le=1440)
    max_videos_per_day: int = Field(default=5, ge=0, le=50)
    start_mode: Literal["new_only", "last_n"] = "new_only"
    initial_limit: int = Field(default=10, ge=1, le=50)
    include_keywords: list[str] | None = None
    exclude_keywords: list[str] | None = None
    borderline_policy: Literal["hold", "continue"] = "hold"
    mismatch_policy: Literal["reject", "hold"] = "reject"
    order: Literal["oldest_first", "newest_first"] = "oldest_first"


class SourceCookieSave(BaseModel):
    cookie: str = Field(min_length=1, max_length=200000)


class SourceCookieStatus(BaseModel):
    configured: bool = False
    status: str = "missing"
    account_name: str | None = None
    verified_at: datetime | None = None
    needs_reauth: bool = False


class SourceCookieTestResponse(BaseModel):
    ok: bool = True
    nickname: str | None = None
    sec_uid: str | None = None
    latest_aweme_id: str | None = None


class ChannelAutoStatus(BaseModel):
    auto_enabled: bool = False
    sources_count: int = 0
    enabled_sources: int = 0
    needs_reauth_sources: int = 0
    last_scan_at: datetime | None = None
    next_scan_at: datetime | None = None
    today_published: int = 0
    today_limit: int = 0
    queue_count: int = 0
    failed_count: int = 0
    held_count: int = 0
    rejected_count: int = 0

