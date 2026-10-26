from pathlib import Path
from typing import Any

from pydantic import AliasChoices, Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # --- Core ---
    service_name: str = "backend-tiktok"
    version: str = "1.0.0"
    port: int = 8000
    log_level: str = "INFO"

    admin_token: str = "CHANGE_ME_LONG_RANDOM_TOKEN"

    # --- Database (Turso / libsql) ---
    turso_database_url: str = Field(default="")
    turso_auth_token: str = Field(
        default="",
        validation_alias=AliasChoices("TURSO_AUTH_TOKEN", "TURSO_TOKEN"),
    )

    cors_origins: str = "*"

    # --- Media download ---
    tiktok_media_max_bytes: int = 1_000_000_000
    tiktok_scan_write_chunk: int = 100

    # --- Manual resolver (PHIMTAT shortcut provider) ---
    tiktok_manual_resolver: str = "shortcut"
    phimtat_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("PHIMTAT_ENABLED"),
    )
    phimtat_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("PHIMTAT_API_KEY"),
    )
    phimtat_api_base_url: str = Field(
        default="https://api.phimtat.vn/json/snapvideo.json",
        validation_alias=AliasChoices("PHIMTAT_API_BASE_URL"),
    )
    phimtat_redirect_url: str = Field(
        default="https://api.phimtat.vn/snapvideo/red64.php",
        validation_alias=AliasChoices("PHIMTAT_REDIRECT_URL"),
    )
    phimtat_timeout_seconds: float = Field(
        default=60.0,
        validation_alias=AliasChoices("PHIMTAT_TIMEOUT_SECONDS"),
    )
    phimtat_ver: str = Field(
        default="8",
        validation_alias=AliasChoices("PHIMTAT_VER"),
    )
    phimtat_max_bytes: int = Field(
        default=500 * 1024 * 1024,
        validation_alias=AliasChoices("PHIMTAT_MAX_BYTES"),
    )

    # --- TikTok Source API (scan + metadata provider) ---
    tiktok_source_api_base_url: str = Field(
        default="https://tiktok-api-xzze.onrender.com",
        validation_alias=AliasChoices("TIKTOK_SOURCE_API_BASE_URL"),
    )
    tiktok_source_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("TIKTOK_SOURCE_API_KEY"),
    )
    tiktok_source_timeout_seconds: float = Field(
        default=120.0,
        validation_alias=AliasChoices("TIKTOK_SOURCE_TIMEOUT_SECONDS"),
    )
    tiktok_source_max_count: int = Field(
        default=30,
        validation_alias=AliasChoices("TIKTOK_SOURCE_MAX_COUNT"),
    )

    # --- YouTube OAuth ---
    tiktok_youtube_callback_url: str = Field(
        default="https://tiktok-api.toolnet.tech/api/tiktok/youtube/oauth/callback",
        validation_alias=AliasChoices("TIKTOK_YOUTUBE_CALLBACK_URL", "tiktok_youtube_callback_url"),
    )
    google_client_id: str = Field(
        default="",
        validation_alias=AliasChoices("GOOGLE_CLIENT_ID"),
    )
    google_client_secret: str = Field(
        default="",
        validation_alias=AliasChoices("GOOGLE_CLIENT_SECRET"),
    )
    dashboard_base_url: str = Field(
        default="https://douyin.toolnet.tech",
        validation_alias=AliasChoices("DASHBOARD_BASE_URL", "NEXT_PUBLIC_APP_URL", "dashboard_base_url"),
    )

    # --- AI / ToolNet ---
    toolnet_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("TOOLNET_BASE_URL", "AI_TOOLNET_URL"),
    )
    toolnet_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("TOOLNET_API_KEY", "AI_API_KEY"),
    )
    toolnet_model: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices("TOOLNET_MODEL", "AI_TOOLNET_MODEL"),
    )
    toolnet_fallback_model: str = Field(
        default="",
        validation_alias=AliasChoices("TOOLNET_FALLBACK_MODEL", "AI_TOOLNET_FAILBACK_MODEL"),
    )
    toolnet_ai_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("TOOLNET_AI_ENABLED"),
    )
    toolnet_timeout: float = 60.0
    toolnet_max_requests_per_minute: int = 30
    toolnet_max_tokens_per_minute: int = 8000

    # --- Active provider selector ---
    tiktok_provider: str = "source_api"
    tiktok_source_scraper_enabled: bool = True

    # --- Scheduler ---
    tiktok_scheduler_enabled: bool = False
    tiktok_scheduler_batch_time: str = "06:00"
    tiktok_scheduler_poll_seconds: int = 30

    # --- Publisher ---
    tiktok_publisher_enabled: bool = False

    # --- Caches ---
    tiktok_flow_cache_seconds: int = 10
    tiktok_schedule_status_cache_seconds: int = 40

    # --- Reconciler ---
    tiktok_reconcile_enabled: bool = False
    tiktok_reconcile_poll_seconds: int = 300

    # --- Quota pause ---
    tiktok_quota_pause_minutes: int = 60

    # --- Paths ---
    tmp_root: Path = Path("/tmp/tiktok")

    @property
    def allowed_hosts(self) -> set[str]:
        return {"www.tiktok.com", "tiktok.com", "vm.tiktok.com", "vt.tiktok.com"}

    @field_validator(
        "phimtat_timeout_seconds", "toolnet_timeout",
        "tiktok_source_timeout_seconds",
        mode="before",
    )
    @classmethod
    def _coerce_float(cls, v: Any, info: ValidationInfo) -> float:
        defaults = {
            "phimtat_timeout_seconds": 60.0,
            "toolnet_timeout": 60.0,
            "tiktok_source_timeout_seconds": 120.0,
        }
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return defaults.get(info.field_name, 60.0)
        try:
            return float(v)
        except (ValueError, TypeError):
            return defaults.get(info.field_name, 60.0)

    @field_validator(
        "tiktok_scan_write_chunk", "tiktok_scheduler_poll_seconds",
        "tiktok_reconcile_poll_seconds", "tiktok_quota_pause_minutes",
        "tiktok_flow_cache_seconds", "tiktok_schedule_status_cache_seconds",
        "tiktok_source_max_count",
        mode="before",
    )
    @classmethod
    def _coerce_int(cls, v: Any, info: ValidationInfo) -> int:
        defaults = {
            "tiktok_scan_write_chunk": 100,
            "tiktok_scheduler_poll_seconds": 30,
            "tiktok_reconcile_poll_seconds": 300,
            "tiktok_quota_pause_minutes": 60,
            "tiktok_flow_cache_seconds": 10,
            "tiktok_schedule_status_cache_seconds": 40,
            "tiktok_source_max_count": 30,
        }
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return defaults.get(info.field_name, 0)
        try:
            return int(v)
        except (ValueError, TypeError):
            return defaults.get(info.field_name, 0)


settings = Settings()
