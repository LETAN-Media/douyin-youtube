import os
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Douyin YouTube Automation"

    database_url: str
    admin_token: str

    public_base_url: str = "http://localhost:8000"

    frontend_url: str = ""

    google_client_id: str = ""
    google_client_secret: str = ""

    cors_origins: str = "*"

    worker_enabled: bool = True
    worker_poll_seconds: int = 5

    temp_dir: str = "/tmp/douyin-youtube"

    # Optional Netscape cookies.txt encoded with base64.
    douyin_cookies_b64: str = ""

    # Optional key for encrypting saved Douyin login sessions at rest.
    # Falls back to ADMIN_TOKEN-derived key when empty.
    session_encryption_key: str = ""

    # Preferred key for per-source Douyin cookie encryption (Fernet via
    # SHA-256 digest). Falls back to SESSION_ENCRYPTION_KEY then ADMIN_TOKEN.
    app_encryption_key: str = ""

    # QR login flow budget (seconds the backend waits for a QR scan).
    douyin_login_timeout_seconds: int = 300

    # Optional AI metadata generator
    ai_enabled: bool = True
    ai_base_url: str = "https://api.toolnet.tech/v1"
    ai_api_key: str = ""
    ai_model: str = "alims-intl.llm"

    # Optional Rcuts configuration (centralized in /root/douyin-youtube/.env)
    # New canonical env names: RCUTS_API, RCUTS_PRIMARY_API, RCUTS_FALLBACK_API
    # Keep legacy rcuts_*_url fields for backward compat.
    rcuts_api_url: str = Field(
        default="http://api.rcuts.com/Video/DouYin.php",
        validation_alias="RCUTS_API_URL",
    )
    rcuts_api: str = Field(default="", validation_alias="RCUTS_API")
    rcuts_token: str = ""
    rcuts_update_url: str = "http://i.rcuts.com/update/247"

    rcuts_primary_api_url: str = Field(
        default="http://api.rcuts.com/Video/DouYin_All.php",
        validation_alias="RCUTS_PRIMARY_API_URL",
    )
    rcuts_primary_api: str = Field(default="", validation_alias="RCUTS_PRIMARY_API")
    rcuts_primary_update_url: str = "http://i.rcuts.com/update/249"
    rcuts_fallback_api_url: str = Field(
        default="http://api.rcuts.com/Video/DouYin.php",
        validation_alias="RCUTS_FALLBACK_API_URL",
    )
    rcuts_fallback_api: str = Field(default="", validation_alias="RCUTS_FALLBACK_API")
    rcuts_fallback_update_url: str = "http://i.rcuts.com/update/247"

    @model_validator(mode="after")
    def _apply_rcuts_aliases(self) -> "Settings":
        # Prefer new canonical RCUTS_* vars if set; fall back to legacy.
        # Also allow RCUTS_API to feed rcuts_api_url for minimal config.
        if self.rcuts_api and self.rcuts_api.strip():
            self.rcuts_api_url = self.rcuts_api.strip()
        # RCUTS_API env without suffix should also be readable via os.environ
        # (pydantic alias already handles RCUTS_API), but also check direct env
        # for cases where .env is at project root.
        env_rcuts = os.getenv("RCUTS_API", "").strip()
        if env_rcuts:
            self.rcuts_api_url = env_rcuts
        env_primary = os.getenv("RCUTS_PRIMARY_API", "").strip() or self.rcuts_primary_api.strip()
        if env_primary:
            self.rcuts_primary_api_url = env_primary
        env_fallback = os.getenv("RCUTS_FALLBACK_API", "").strip() or self.rcuts_fallback_api.strip()
        if env_fallback:
            self.rcuts_fallback_api_url = env_fallback
        return self

    # Monitor configuration
    monitor_enabled: bool = True
    monitor_poll_seconds: int = 300
    monitor_startup_delay_seconds: int = 10

    # AUTO source scan configuration
    auto_scan_interval_minutes: int = 15
    douyin_scan_concurrency: int = 2

    # Douyin browser inventory configuration
    max_inventory_pages: int = 200
    douyin_inventory_concurrency: int = 1

    # Scheduler configuration
    scheduler_enabled: bool = True
    scheduler_poll_seconds: int = 60
    scheduler_startup_delay_seconds: int = 10

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url.strip()

        if url.startswith("postgresql+psycopg://"):
            return url

        if url.startswith("postgresql://"):
            return url.replace(
                "postgresql://",
                "postgresql+psycopg://",
                1,
            )

        if url.startswith("postgres://"):
            return url.replace(
                "postgres://",
                "postgresql+psycopg://",
                1,
            )

        return url

    @property
    def youtube_callback_url(self) -> str:
        return (
            f"{self.public_base_url.rstrip('/')}"
            "/auth/youtube/callback"
        )

    @property
    def allowed_origins(self) -> list[str]:
        value = self.cors_origins.strip()

        if value == "*":
            return ["*"]

        return [
            item.strip()
            for item in value.split(",")
            if item.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
