"""Environment-backed application configuration."""

from functools import lru_cache
from typing import Literal
from urllib.parse import quote

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from the local .env file or environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    postgres_db: str = "sme_bridge"
    postgres_user: str = "sme_bridge"
    postgres_password: SecretStr = SecretStr("")
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("")
    bizinfo_api_key: SecretStr | None = None
    storage_backend: Literal["postgres", "sqlite"] = "postgres"
    sqlite_path: str = "data/local/bridge.sqlite3"

    @model_validator(mode="after")
    def validate_backend_credentials(self) -> "Settings":
        if self.storage_backend == "postgres" and (
            not self.postgres_password.get_secret_value()
            or not self.neo4j_password.get_secret_value()
        ):
            raise ValueError("PostgreSQL mode requires POSTGRES_PASSWORD and NEO4J_PASSWORD")
        return self

    @property
    def postgres_dsn(self) -> str:
        """Build an asyncpg DSN while safely escaping credentials."""
        user = quote(self.postgres_user, safe="")
        password = quote(self.postgres_password.get_secret_value(), safe="")
        database = quote(self.postgres_db, safe="")
        return (
            f"postgresql://{user}:{password}@{self.postgres_host}:{self.postgres_port}/{database}"
        )


@lru_cache
def get_settings() -> Settings:
    """Return one immutable-style settings instance per process."""
    return Settings()
