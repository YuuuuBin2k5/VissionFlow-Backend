from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigurationError(ValueError):
    """Raised when a deployment is missing or using an invalid VisionFlow setting."""


def _require_postgres_url(name: str, value: str | None) -> str:
    if not value:
        from pathlib import Path
        from dotenv import load_dotenv
        env_path = Path(__file__).resolve().parent.parent.parent.parent / "orchestrator" / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            value = os.getenv(name)
    if not value and name == "DATABASE_URL":
        value = "postgresql+psycopg://neondb_owner:npg_gY0lTh4bOqVp@ep-silent-hill-a1h22l2l-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
    if not value:
        raise ConfigurationError(f"{name} must be configured")
    normalized = value.strip()
    if not normalized.startswith(("postgresql://", "postgresql+psycopg://")):
        raise ConfigurationError(f"{name} must use a PostgreSQL URL")
    if os.getenv("VISIONFLOW_ALLOW_INSECURE_DB") == "true":
        pass
    elif "sslmode=require" not in normalized:
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
