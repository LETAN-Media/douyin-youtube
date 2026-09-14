from functools import lru_cache

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

    # Optional AI metadata generator
    ai_enabled: bool = True
    ai_base_url: str = "https://api.toolnet.tech/v1"
    ai_api_key: str = ""
    ai_model: str = "alims-intl.llm"

    # Optional Rcuts configuration
    rcuts_api_url: str = "http://api.rcuts.com/Video/DouYin.php"
    rcuts_token: str = ""
    rcuts_update_url: str = "http://i.rcuts.com/update/247"

    # Optional Rcuts primary/fallback configuration
    rcuts_primary_api_url: str = "http://api.rcuts.com/Video/DouYin_All.php"
    rcuts_primary_update_url: str = "http://i.rcuts.com/update/249"
    rcuts_fallback_api_url: str = "http://api.rcuts.com/Video/DouYin.php"
    rcuts_fallback_update_url: str = "http://i.rcuts.com/update/247"

    # Monitor configuration
    monitor_enabled: bool = True
    monitor_poll_seconds: int = 300
    monitor_startup_delay_seconds: int = 10

    # Scheduler configuration
    scheduler_enabled: bool = True
    scheduler_poll_seconds: int = 60
    scheduler_startup_delay_seconds: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
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
