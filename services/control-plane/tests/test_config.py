import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.core.config import ConfigurationError, Settings  # noqa: E402


class SettingsTests(unittest.TestCase):
    def test_accepts_postgres_urls_with_tls(self) -> None:
        env = {
            "DATABASE_URL": "postgresql+psycopg://app:secret@pooler.example/visionflow?sslmode=require",
            "MIGRATION_DATABASE_URL": "postgresql+psycopg://migrator:secret@direct.example/visionflow?sslmode=require",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings.from_env(require_migration_url=True)
        self.assertEqual(settings.app_env, "local")
        self.assertIsNotNone(settings.migration_database_url)

    def test_normalizes_neon_standard_urls_to_the_installed_psycopg_driver(self) -> None:
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "postgresql://app:secret@pooler.example/visionflow?sslmode=require"},
            clear=True,
        ):
            settings = Settings.from_env()
        self.assertEqual(
            settings.database_url,
            "postgresql+psycopg://app:secret@pooler.example/visionflow?sslmode=require",
        )

    def test_rejects_mysql(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": "mysql+pymysql://root:secret@localhost/app"}, clear=True):
            with self.assertRaises(ConfigurationError):
                Settings.from_env()

    def test_requires_tls(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql+psycopg://app:secret@db.example/visionflow"}, clear=True):
            with self.assertRaises(ConfigurationError):
                Settings.from_env()
