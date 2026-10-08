from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    SERVICE_NAME: str = "backend-audio"
    VERSION: str = "0.1.0"
    APP_ENV: str = "development"
    PORT: int = 8080
    LOG_LEVEL: str = "INFO"

    AUDIO_ADMIN_TOKEN: str | None = None

    # Turso (libSQL over HTTPS). The shared HTTP client below is used
    # instead of libsql_client (its sync execute() hangs in some sandboxes).
    AUDIO_TURSO_URL: str | None = None
    AUDIO_TURSO_TOKEN: str | None = None
    AUDIO_DB_PATH: str = "/tmp/backend_audio.sqlite3"

    # Google OAuth for YouTube (dedicated Audio callback + own Fernet key;
    # never shared with drama/facebook credential stores).
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    AUDIO_YOUTUBE_CALLBACK_URL: str = (
        "https://audio-api.toolnet.tech/api/audio/youtube/oauth/callback"
    )
    AUDIO_DASHBOARD_URL: str = "https://douyin.toolnet.tech"
    AUDIO_TOKEN_ENCRYPTION_KEY: str | None = None

    # SnapVideo / PHIMTAT download resolver (same style as backend_facebook).
    PHIMTAT_ENABLED: bool = True
    PHIMTAT_API_KEY: str | None = None
    PHIMTAT_API_BASE_URL: str = "https://api.phimtat.vn/json/snapvideo.json"
    PHIMTAT_TIMEOUT_SECONDS: float = 60.0
    PHIMTAT_MAX_BYTES: int = 500 * 1024 * 1024

    # ToolNet OpenAI-compatible AI (read-only from env, never logged).
    TOOLNET_BASE_URL: str | None = None
    TOOLNET_API_KEY: str | None = None
    TOOLNET_MODEL: str | None = None
    TOOLNET_AI_ENABLED: bool = True
    TOOLNET_TIMEOUT: float = 60.0
    TOOLNET_MAX_REQUESTS_PER_MINUTE: int = 30
    TOOLNET_MAX_TOKENS_PER_MINUTE: int = 8000

    # Cloudflare R2 (S3-compatible) media library.
    R2_ACCOUNT_ID: str | None = None
    R2_ACCESS_KEY_ID: str | None = None
    R2_SECRET_ACCESS_KEY: str | None = None
    R2_BUCKET: str | None = None
    R2_PUBLIC_BASE_URL: str | None = None

    # Resource bounds for small Northflank compute.
    AUDIO_WORKER_CONCURRENCY: int = 1
    AUDIO_RENDER_CONCURRENCY: int = 1
    AUDIO_FFMPEG_THREADS: int = 2
    AUDIO_JOB_TIMEOUT_SECONDS: int = 7200
    AUDIO_WORKDIR: str = "/tmp/backend-audio/jobs"
    AUDIO_MAX_UPLOAD_BYTES: int = 2 * 1024 * 1024 * 1024

    # Optional JianYing ASR bridge (node). Empty = ASR disabled.
    JIANYING_BRIDGE_DIR: str | None = None

    def require_toolnet(self) -> tuple[str, str, str]:
        base_url = (self.TOOLNET_BASE_URL or "").strip().rstrip("/")
        api_key = (self.TOOLNET_API_KEY or "").strip()
        model = (self.TOOLNET_MODEL or "").strip()
        if not base_url or not api_key or not model:
            raise RuntimeError(
                "TOOLNET_BASE_URL / TOOLNET_API_KEY / TOOLNET_MODEL are not configured."
            )
        return base_url, api_key, model

    def r2_configured(self) -> bool:
        return bool(
            (self.R2_ACCOUNT_ID or "").strip()
            and (self.R2_ACCESS_KEY_ID or "").strip()
            and (self.R2_SECRET_ACCESS_KEY or "").strip()
            and (self.R2_BUCKET or "").strip()
        )


settings = Settings()
