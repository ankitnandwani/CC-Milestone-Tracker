from functools import cached_property, lru_cache
from urllib.parse import quote_plus

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "CCGeek"
    app_env: str = "development"

    db_host: str
    db_port: int = 5432
    db_name: str = "postgres"
    db_user: str
    db_password: str
    db_ssl_mode: str = "require"

    microsoft_client_id: str
    microsoft_tenant_id: str = "common"
    microsoft_mailbox_username: str | None = None

    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    @cached_property
    def _encoded_password(self) -> str:
        return quote_plus(self.db_password)

    @computed_field
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://"
            f"{self.db_user}:{self._encoded_password}"
            f"@{self.db_host}:{self.db_port}"
            f"/{self.db_name}"
            f"?sslmode={self.db_ssl_mode}"
        )

    @computed_field
    @property
    def async_database_url(self) -> str:
        return (
            f"postgresql+psycopg_async://"
            f"{self.db_user}:{self._encoded_password}"
            f"@{self.db_host}:{self.db_port}"
            f"/{self.db_name}"
            f"?sslmode={self.db_ssl_mode}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
