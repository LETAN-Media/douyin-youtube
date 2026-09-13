from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Douyin YouTube Automation"

    database_url: str
    admin_token: str

    public_base_url: str = "http://localhost:8000"

    google_client_id: str = ""
    google_client_secret: str = ""

    cors_origins: str = "*"

    worker_enabled: bool = True
    worker_poll_seconds: int = 5

    temp_dir: str = "/tmp/douyin-youtube"

    # Optional Netscape cookies.txt encoded with base64.
    douyin_cookies_b64: str = ""

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
