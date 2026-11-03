from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    SERVICE_NAME: str = "backend-youtube"
    VERSION: str = "1.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    ADMIN_TOKEN: str | None = None
    CORS_ORIGINS: str = "*"

    DATABASE_URL: str | None = None
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: float = 30.0
    DB_ECHO: bool = False
    DB_SSL_MODE: str = "require"

    YOUTUBE_DATA_API_KEY: str | None = None
    YOUTUBE_API_TIMEOUT: float = 30.0
    YOUTUBE_SCAN_MAX_RESULTS: int = 50
    YOUTUBE_SCAN_MAX_PAGES: int = 500
    YOUTUBE_SCAN_WRITE_CHUNK: int = 50

    FACEBOOK_APP_ID: str | None = None
    FACEBOOK_APP_SECRET: str | None = None
    FACEBOOK_PAGE_ACCESS_TOKEN: str | None = None
    FACEBOOK_GRAPH_API_VERSION: str = "v19.0"
    FACEBOOK_GRAPH_BASE_URL: str = "https://graph.facebook.com"
    FACEBOOK_API_TIMEOUT: float = 60.0
    FACEBOOK_UPLOAD_TIMEOUT: float = 600.0
    FACEBOOK_MEDIA_MAX_BYTES: int = 1_000_000_000
    FACEBOOK_REEL_MAX_SECONDS: int = 90
    FACEBOOK_REEL_MAX_BYTES: int = 4_000_000_000
    FACEBOOK_VIDEO_MAX_BYTES: int = 4_000_000_000

    TOOLNET_BASE_URL: str | None = None
    TOOLNET_API_KEY: str | None = None
    TOOLNET_MODEL: str | None = None
    TOOLNET_MODELS: str | None = None
    TOOLNET_AI_ENABLED: bool = False
    TOOLNET_TIMEOUT: float = 60.0
    TOOLNET_MAX_REQUESTS_PER_MINUTE: int = 30
    TOOLNET_MAX_TOKENS_PER_MINUTE: int = 8000

    YOUTUBE_OAUTH_CLIENT_ID: str | None = None
    YOUTUBE_OAUTH_CLIENT_SECRET: str | None = None
    YOUTUBE_OAUTH_REDIRECT_URI: str | None = None

    SCHEDULER_ENABLED: bool = True
    SCHEDULER_POLL_SECONDS: int = 30
    SCHEDULER_BATCH_TIME: str = "06:00"
    SCHEDULER_SLOT_WINDOW_MINUTES: int = 60
    SCHEDULER_JITTER_MINUTES: int = 0
    SCHEDULER_SLOT_DEFAULT_MAX_DAILY: int = 5
    SCHEDULER_SLOT_DEFAULT_TIMEZONE: str = "Asia/Ho_Chi_Minh"

    PUBLISH_WORKER_ENABLED: bool = True
    PUBLISH_CONCURRENCY: int = 1
    PUBLISH_POLL_SECONDS: int = 5
    PUBLISH_STALE_TTL_SECONDS: int = 300
    QUOTA_PAUSE_MINUTES: int = 60
    RETRY_MAX_ATTEMPTS: int = 5
    RETRY_BASE_BACKOFF_SECONDS: int = 60

    AI_WORKER_ENABLED: bool = True
    AI_WORKER_CONCURRENCY: int = 1
    AI_WORKER_POLL_SECONDS: int = 10
    AI_WORKER_STALE_TTL_SECONDS: int = 300
    AI_MAX_RETRIES: int = 3
    AI_RETRY_BACKOFF_SECONDS: int = 300

    AUTO_RESCAN_THRESHOLD_PCT: int = 20
    DEFAULT_MAX_DAILY_PUBLISH: int = 5

    DASHBOARD_BASE_URL: str = "https://douyin.toolnet.tech"
    YOUTUBE_MANUAL_RESOLVER: str = "ytdlp"
    FASTSAVER_BASE_URL: str = "https://api.fastsaver.io/v1"
    FASTSAVER_API_KEY: str | None = None
    FASTSAVER_TIMEOUT: float = 60.0

    def require_database_url(self) -> str:
        url = (self.DATABASE_URL or "").strip()
        if not url:
            raise RuntimeError("DATABASE_URL is not configured.")
        if url.startswith("sqlite://") and url != "sqlite+aiosqlite:///:memory:":
            if "memory" not in url:
                raise RuntimeError("SQLite file URLs are forbidden in production; use a Neon PostgreSQL DATABASE_URL.")
        return url

    def require_toolnet(self) -> tuple[str, str, str]:
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

    def require_fastsaver(self) -> tuple[str, str]:
        if not self.FASTSAVER_API_KEY:
            raise RuntimeError("FASTSAVER_API_KEY is not configured.")
        return self.FASTSAVER_BASE_URL.rstrip("/"), self.FASTSAVER_API_KEY

    def require_facebook(self) -> tuple[str, str, str, str]:
        missing = []
        if not (self.FACEBOOK_APP_ID or "").strip():
            missing.append("FACEBOOK_APP_ID")
        if not (self.FACEBOOK_APP_SECRET or "").strip():
            missing.append("FACEBOOK_APP_SECRET")
        if not (self.FACEBOOK_PAGE_ACCESS_TOKEN or "").strip():
            missing.append("FACEBOOK_PAGE_ACCESS_TOKEN")
        if missing:
            raise RuntimeError(f"Missing Facebook config: {', '.join(missing)}")
        return (
            self.FACEBOOK_APP_ID.strip(),
            self.FACEBOOK_APP_SECRET.strip(),
            self.FACEBOOK_PAGE_ACCESS_TOKEN.strip(),
            self.FACEBOOK_GRAPH_API_VERSION,
        )

    def redact(self, message: str | None) -> str:
        redacted = message or ""
        for secret in (
            self.ADMIN_TOKEN,
            self.DATABASE_URL,
            self.FACEBOOK_PAGE_ACCESS_TOKEN,
            self.FACEBOOK_APP_SECRET,
            self.TOOLNET_API_KEY,
            self.YOUTUBE_DATA_API_KEY,
            self.FASTSAVER_API_KEY,
            self.YOUTUBE_OAUTH_CLIENT_SECRET,
        ):
            if secret and len(str(secret)) > 4 and secret in redacted:
                redacted = redacted.replace(secret, "***")
        return redacted[:800]


settings = Settings()
