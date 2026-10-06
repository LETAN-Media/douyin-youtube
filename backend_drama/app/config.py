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
    # RAPIDAPI_KEY is accepted as an alias (same RapidAPI account key).
    RAPIDIX_KEY: str | None = None
    RAPIDAPI_KEY: str | None = None
    RAPIDAPI_HOST: str | None = None
    RAPIDAPI_BASE_URL: str | None = None
    # Exact endpoint paths are NOT guessed: they must be copied from the
    # provider's RapidAPI playground code snippets. Until set, provider
    # methods raise NOT_CONFIGURED and live calls are refused.
    RAPIDIX_SEARCH_PATH: str | None = None
    RAPIDIX_EPISODES_PATH: str | None = None
    RAPIDIX_EPISODE_PATH: str | None = None
    RAPIDIX_TIMEOUT_SECONDS: float = 30.0

    # Short Drama Pro hub (multi-provider, RapidAPI marketplace).
    # Canonical config for new provider adapters; RAPIDIX_* stay for
    # backward compatibility with existing rapidix data.
    DRAMA_API_HOST: str = "short-drama-pro.p.rapidapi.com"
    DRAMA_API_KEY: str | None = None
    DRAMA_API_BASE_URL: str = "https://short-drama-pro.p.rapidapi.com"
    DRAMA_API_TIMEOUT_SECONDS: float = 30.0
    # Provider failover pool: 1 primary + up to 4 fallbacks. Each slot needs
    # HOST + KEY (BASE_URL defaults to https://{HOST}). Optional _PROVIDERS
    # limits the slot to content providers (comma-separated, empty = all).
    DRAMA_API_PRIMARY_HOST: str | None = None
    DRAMA_API_PRIMARY_BASE_URL: str | None = None
    DRAMA_API_PRIMARY_KEY: str | None = None
    DRAMA_API_PRIMARY_PROVIDERS: str | None = None
    DRAMA_API_FALLBACK_1_HOST: str | None = None
    DRAMA_API_FALLBACK_1_BASE_URL: str | None = None
    DRAMA_API_FALLBACK_1_KEY: str | None = None
    DRAMA_API_FALLBACK_1_PROVIDERS: str | None = None
    DRAMA_API_FALLBACK_2_HOST: str | None = None
    DRAMA_API_FALLBACK_2_BASE_URL: str | None = None
    DRAMA_API_FALLBACK_2_KEY: str | None = None
    DRAMA_API_FALLBACK_2_PROVIDERS: str | None = None
    DRAMA_API_FALLBACK_3_HOST: str | None = None
    DRAMA_API_FALLBACK_3_BASE_URL: str | None = None
    DRAMA_API_FALLBACK_3_KEY: str | None = None
    DRAMA_API_FALLBACK_3_PROVIDERS: str | None = None
    DRAMA_API_FALLBACK_4_HOST: str | None = None
    DRAMA_API_FALLBACK_4_BASE_URL: str | None = None
    DRAMA_API_FALLBACK_4_KEY: str | None = None
    DRAMA_API_FALLBACK_4_PROVIDERS: str | None = None

    def rapidix_key(self) -> str:
        return ((self.RAPIDIX_KEY or "") or (self.RAPIDAPI_KEY or "")).strip()

    def drama_api_key(self) -> str:
        return (
            (self.DRAMA_API_KEY or "") or self.rapidix_key()
        ).strip()

    def drama_api_configured(self) -> bool:
        return bool(
            self.drama_api_key()
            and (self.DRAMA_API_HOST or "").strip()
            and (self.DRAMA_API_BASE_URL or "").strip().rstrip("/")
        )

    def rapidix_configured(self) -> bool:
        return bool(
            self.rapidix_key()
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
