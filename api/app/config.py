"""Application configuration loaded from environment variables."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings object. Values come from the environment."""

    # Postgres
    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_user: str = "ecom"
    postgres_password: str = "ecom_dev_password"
    postgres_db: str = "ecommerce"

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379

    # JWT
    jwt_secret: str = "change_me"
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def sync_database_url(self) -> str:
        """Sync URL for Alembic migrations."""
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def async_database_url(self) -> str:
        """Async URL for FastAPI runtime queries."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
