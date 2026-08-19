"""Application configuration.

Reads the same ``.env`` file as the test framework, but only the ``APP_*`` and
shared database-location values. The application and the framework connect with
*different* database roles: the application owns the schema, the framework may
only read.
"""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Runtime configuration for the ClaimDesk application."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    db_host: str = "localhost"
    db_port: int = 55432
    db_name: str = "claimdesk"
    app_db_user: str = "claimdesk_app"
    app_db_password: SecretStr = SecretStr("change-me-local-only")

    app_jwt_secret: SecretStr = SecretStr("change-me-local-only")
    app_jwt_expiry_minutes: int = Field(default=60, gt=0, le=1440)

    seed_user_password: SecretStr = SecretStr("Passw0rd!seed")
    auto_migrate: bool = True
    """Create tables and seed reference data on startup. True for local and test
    environments; a real deployment would use migrations instead."""

    @property
    def sqlalchemy_url(self) -> str:
        user = quote(self.app_db_user, safe="")
        password = quote(self.app_db_password.get_secret_value(), safe="")
        return (
            f"postgresql+psycopg://{user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache(maxsize=1)
def get_app_settings() -> AppSettings:
    return AppSettings()
