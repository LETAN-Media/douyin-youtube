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


settings = Settings()
