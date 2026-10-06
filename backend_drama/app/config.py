from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    SERVICE_NAME: str = "backend-drama"
    VERSION: str = "0.1.0"
    APP_ENV: str = "development"
    PORT: int = 8080
    LOG_LEVEL: str = "INFO"

    DRAMA_ADMIN_TOKEN: str | None = None

    # Local SQLite file by default. Set a libSQL (Turso) URL for shared
    # production storage in a later phase.
    DRAMA_TURSO_URL: str | None = None
    DRAMA_TURSO_TOKEN: str | None = None
    DRAMA_DB_PATH: str = "/tmp/backend_drama.sqlite3"

    # RapidIX (RapidAPI marketplace, ReelShort unofficial provider).
    # Key lives only in env — never log it, never return it, never commit it.
    RAPIDIX_KEY: str | None = None
    RAPIDAPI_HOST: str | None = None
    RAPIDAPI_BASE_URL: str | None = None
    # Exact endpoint paths are NOT guessed: they must be copied from the
    # provider's RapidAPI playground code snippets. Until set, provider
    # methods raise NOT_CONFIGURED and live calls are refused.
    RAPIDIX_SEARCH_PATH: str | None = None
    RAPIDIX_EPISODES_PATH: str | None = None
    RAPIDIX_EPISODE_PATH: str | None = None
    RAPIDIX_TIMEOUT_SECONDS: float = 30.0

    def rapidix_configured(self) -> bool:
        return bool(
            (self.RAPIDIX_KEY or "").strip()
            and (self.RAPIDAPI_HOST or "").strip()
            and (self.RAPIDAPI_BASE_URL or "").strip().rstrip("/")
        )

    def rapidix_endpoints_configured(self) -> bool:
        return bool(
            (self.RAPIDIX_SEARCH_PATH or "").strip()
            and (self.RAPIDIX_EPISODES_PATH or "").strip()
            and (self.RAPIDIX_EPISODE_PATH or "").strip()
        )

    def db_configured(self) -> bool:
        url = (self.DRAMA_TURSO_URL or "").strip()
        if not url:
            return True  # local SQLite fallback
        return url.startswith("file:")


settings = Settings()
