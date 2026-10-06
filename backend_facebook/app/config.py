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
    # Manual-publish resolver (Task 14): "shortcut" (strict, default),
    # "shortcut_fastsaver" (shortcut first, FastSaver fallback on
    # timeout/temporary/unsupported responses — never on validation or
    # auth errors), or "fastsaver" (legacy behavior). Auto pipeline always
    # uses FastSaver regardless of this setting.
    FACEBOOK_MANUAL_RESOLVER: str = "shortcut"
    # Third-party provider backing the shortcut-derived resolver
    # (audited from the Snap Video shortcut workflow). Key lives only in
    # env/Northflank — never commit it, never log it. PHIMTAT_* are the
    # canonical manual-resolver settings; MANUAL_FB_* are legacy aliases.
    MANUAL_FB_PROVIDER_BASE_URL: str = "https://api.phimtat.vn"
    MANUAL_FB_PROVIDER_API_KEY: str | None = None
    PHIMTAT_ENABLED: bool = True
    PHIMTAT_API_KEY: str | None = None
    PHIMTAT_API_BASE_URL: str = "https://api.phimtat.vn/json/snapvideo.json"
    PHIMTAT_REDIRECT_URL: str = "https://api.phimtat.vn/snapvideo/red64.php"
    PHIMTAT_TIMEOUT_SECONDS: int = 60
    FASTSAVER_TIMEOUT: float = 60.0
    FACEBOOK_MEDIA_MAX_BYTES: int = 1_000_000_000

    # ToolNet AI (OpenAI-compatible). Never log the key, never commit it.
    TOOLNET_BASE_URL: str | None = None
    TOOLNET_API_KEY: str | None = None
    TOOLNET_MODEL: str | None = None
    # Extra models offered in the per-pipeline picker, comma-separated.
    # First entry (or TOOLNET_MODEL when empty) is the default.
    TOOLNET_MODELS: str | None = None
    TOOLNET_AI_ENABLED: bool = False
    TOOLNET_TIMEOUT: float = 60.0
    TOOLNET_MAX_REQUESTS_PER_MINUTE: int = 30
    TOOLNET_MAX_TOKENS_PER_MINUTE: int = 8000

    # Weekly smart scheduler (Task 9). One batch per day per pipeline/destination.
    FACEBOOK_SCHEDULER_ENABLED: bool = False
    FACEBOOK_SCHEDULER_BATCH_TIME: str = "06:00"
    FACEBOOK_SCHEDULER_POLL_SECONDS: int = 30
    FACEBOOK_SCHEDULER_SLOT_WINDOW_MINUTES: int = 60
    SCHEDULER_JITTER_MINUTES: int = 0

    # YouTube scheduled-publication reconciler (Task 10).
    FACEBOOK_RECONCILE_ENABLED: bool = False
    FACEBOOK_RECONCILE_POLL_SECONDS: int = 300

    # Global publisher queue (Task 12).
    FACEBOOK_PUBLISH_CONCURRENCY: int = 1
    FACEBOOK_PUBLISH_POLL_SECONDS: int = 5
    FACEBOOK_PUBLISH_WORKER_ENABLED: bool = True
    FACEBOOK_PUBLISH_STALE_TTL_SECONDS: int = 300

    # AI metadata background worker (Task 13).
    FACEBOOK_AI_WORKER_ENABLED: bool = True
    FACEBOOK_AI_WORKER_CONCURRENCY: int = 1
    FACEBOOK_AI_WORKER_POLL_SECONDS: int = 10
    FACEBOOK_AI_WORKER_STALE_TTL_SECONDS: int = 300
    FACEBOOK_AI_MAX_RETRIES: int = 3
    FACEBOOK_AI_RETRY_BACKOFF_SECONDS: int = 300

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
    # Dashboard origin used only to redirect back after YouTube OAuth when
    # the flow was started with a whitelisted return_to path.
    DASHBOARD_BASE_URL: str = "https://douyin.toolnet.tech"

    def require_fastsaver(self) -> tuple[str, str]:
        """Return (base_url, api_key) or fail fast with a clear config error."""
        if not self.FASTSAVER_API_KEY:
            raise RuntimeError(
                "FASTSAVER_API_KEY is not configured. "
                "Set it in backend_facebook/.env or the Northflank environment."
            )
        return self.FASTSAVER_BASE_URL.rstrip("/"), self.FASTSAVER_API_KEY


settings = Settings()
