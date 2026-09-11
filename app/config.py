from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from a local .env file when present."""

    app_name: str = "Kuwait Smart Park"
    debug: bool = False
    database_url: str = (
        "postgresql+asyncpg://smartpark:smartpark_dev_password@localhost:5432/smartpark"
    )
    secret_key: str = "change-this-development-secret-before-deploying"
    initial_admin_email: str = "admin@smartpark.local"
    initial_admin_password: str = "ChangeMe123!"
    report_reward_points: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="SMART_PARK_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
