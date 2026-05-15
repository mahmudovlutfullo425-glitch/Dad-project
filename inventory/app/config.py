"""Inventory service configuration loaded from environment variables."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Postgres — used only for the durable CommitReservation update
    # and the startup bootstrap from inventory_levels.
    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_user: str = "ecom"
    postgres_password: str = "ecom_dev_password"
    postgres_db: str = "ecommerce"

    # Redis — shared with the api service so stock counters are
    # visible to both. DB 0.
    redis_host: str = "redis"
    redis_port: int = 6379

    # gRPC listener
    inventory_grpc_port: int = 50051

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def async_database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
