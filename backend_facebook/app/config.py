from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    SERVICE_NAME: str = "backend-facebook"
    VERSION: str = "1.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    ADMIN_TOKEN: str | None = None
    CORS_ORIGINS: str = "*"

    TURSO_DATABASE_URL: str | None = None
    TURSO_AUTH_TOKEN: str | None = None

    FACEBOOK_RAPIDAPI_HOST: str | None = None
    FACEBOOK_RAPIDAPI_BASE_URL: str | None = None
    RAPIDAPI_KEY: str | None = None
    RAPIDAPI_KEY_FALLBACK: str | None = None

    FACEBOOK_RAPIDAPI_MAX_PAGES: int = 200
    FACEBOOK_RAPIDAPI_MAX_REELS: int = 5000
    FACEBOOK_RAPIDAPI_TIMEOUT: float = 20.0
    FACEBOOK_SCAN_WRITE_CHUNK: int = 100
    FACEBOOK_INCREMENTAL_KNOWN_PAGES_STOP: int = 2

    # Primary Facebook media resolver (Task 6B). Key lives only in env/Northflank,
    # never hard-coded, never logged, never committed.
    FASTSAVER_BASE_URL: str = "https://api.fastsaver.io/v1"
    FASTSAVER_API_KEY: str | None = None
    FASTSAVER_TIMEOUT: float = 60.0
    FACEBOOK_MEDIA_MAX_BYTES: int = 1_000_000_000

    def require_fastsaver(self) -> tuple[str, str]:
        """Return (base_url, api_key) or fail fast with a clear config error."""
        if not self.FASTSAVER_API_KEY:
            raise RuntimeError(
                "FASTSAVER_API_KEY is not configured. "
                "Set it in backend_facebook/.env or the Northflank environment."
            )
        return self.FASTSAVER_BASE_URL.rstrip("/"), self.FASTSAVER_API_KEY


settings = Settings()
