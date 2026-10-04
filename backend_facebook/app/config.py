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

    # ToolNet AI (OpenAI-compatible). Never log the key, never commit it.
    TOOLNET_BASE_URL: str | None = None
    TOOLNET_API_KEY: str | None = None
    TOOLNET_MODEL: str | None = None
    TOOLNET_AI_ENABLED: bool = False
    TOOLNET_TIMEOUT: float = 60.0
    TOOLNET_MAX_REQUESTS_PER_MINUTE: int = 30
    TOOLNET_MAX_TOKENS_PER_MINUTE: int = 8000

    # Weekly smart scheduler (Task 9). One batch per day per pipeline/destination.
    FACEBOOK_SCHEDULER_ENABLED: bool = False
    FACEBOOK_SCHEDULER_BATCH_TIME: str = "06:00"
    FACEBOOK_SCHEDULER_POLL_SECONDS: int = 30
    SCHEDULER_JITTER_MINUTES: int = 0

    # YouTube scheduled-publication reconciler (Task 10).
    FACEBOOK_RECONCILE_ENABLED: bool = False
    FACEBOOK_RECONCILE_POLL_SECONDS: int = 300

    def require_toolnet(self) -> tuple[str, str, str]:
        """Return (base_url, api_key, model) or fail fast with a clear config error."""
        if not self.TOOLNET_AI_ENABLED:
            raise RuntimeError("TOOLNET_AI_ENABLED is not true.")
        missing = []
        if not (self.TOOLNET_BASE_URL or "").strip():
            missing.append("TOOLNET_BASE_URL")
        if not (self.TOOLNET_API_KEY or "").strip():
            missing.append("TOOLNET_API_KEY")
        if not (self.TOOLNET_MODEL or "").strip():
            missing.append("TOOLNET_MODEL")
        if missing:
            raise RuntimeError(f"Missing ToolNet AI config: {', '.join(missing)}")
        base = (self.TOOLNET_BASE_URL or "").strip().rstrip("/")
        return base, (self.TOOLNET_API_KEY or "").strip(), (self.TOOLNET_MODEL or "").strip()

    # Google OAuth (YouTube destinations). Read ONLY from existing env:
    # GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET. Never logged, never committed.
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    FACEBOOK_YOUTUBE_CALLBACK_URL: str | None = None

    def require_fastsaver(self) -> tuple[str, str]:
        """Return (base_url, api_key) or fail fast with a clear config error."""
        if not self.FASTSAVER_API_KEY:
            raise RuntimeError(
                "FASTSAVER_API_KEY is not configured. "
                "Set it in backend_facebook/.env or the Northflank environment."
            )
        return self.FASTSAVER_BASE_URL.rstrip("/"), self.FASTSAVER_API_KEY


settings = Settings()
