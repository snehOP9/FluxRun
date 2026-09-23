from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://fluxrun:fluxrun@localhost:5432/fluxrun"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:5173"
    session_cookie_secure: bool = False
    session_ttl_hours: int = 168
    local_admin_email: str | None = None
    local_admin_password: str | None = None
    environment: str = "development"
    s3_endpoint: str = "http://localhost:59000"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "fluxrun-artifacts"
    max_artifact_bytes: int = 33554432
    max_request_bytes: int = 2097152
    encryption_key: str = ""
    signup_enabled: bool = True
    metrics_enabled: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
