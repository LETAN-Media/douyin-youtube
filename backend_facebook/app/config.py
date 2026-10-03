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


settings = Settings()
