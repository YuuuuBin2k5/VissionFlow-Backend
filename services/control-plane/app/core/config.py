from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigurationError(ValueError):
    """Raised when a deployment is missing or using an invalid VisionFlow setting."""


def _require_postgres_url(name: str, value: str | None) -> str:
    if not value:
        raise ConfigurationError(f"{name} must be configured")
    normalized = value.strip()
    if not normalized.startswith(("postgresql://", "postgresql+psycopg://")):
        raise ConfigurationError(f"{name} must use a PostgreSQL URL")
    if "sslmode=require" not in normalized:
        raise ConfigurationError(f"{name} must require TLS with sslmode=require")
    # Neon presents standard PostgreSQL URLs. SQLAlchemy otherwise chooses the
    # unavailable psycopg2 dialect for that scheme, while this service ships
    # the modern `psycopg` driver. Keep the operator-facing URL conventional
    # and select the installed driver at this infrastructure boundary.
    if normalized.startswith("postgresql://"):
        normalized = f"postgresql+psycopg://{normalized.removeprefix('postgresql://')}"
    return normalized


@dataclass(frozen=True)
class Settings:
    app_env: str
    api_prefix: str
    database_url: str
    migration_database_url: str | None

    @classmethod
    def from_env(cls, *, require_migration_url: bool = False) -> "Settings":
        migration_value = os.getenv("MIGRATION_DATABASE_URL")
        migration_url = (
            _require_postgres_url("MIGRATION_DATABASE_URL", migration_value)
            if migration_value
            else None
        )
        if require_migration_url and migration_url is None:
            raise ConfigurationError("MIGRATION_DATABASE_URL must be configured for Alembic")
        return cls(
            app_env=os.getenv("APP_ENV", "local").strip() or "local",
            api_prefix=os.getenv("API_PREFIX", "/api/v1").rstrip("/"),
            database_url=_require_postgres_url("DATABASE_URL", os.getenv("DATABASE_URL")),
            migration_database_url=migration_url,
        )
