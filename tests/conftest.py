"""
Global pytest configuration for VisionFlow Backend tests.
Ensures tests run deterministically offline using development repositories,
preventing remote database latency or external cloud API deadlocks during test runs.
"""

import os
import pytest
from production.repositories.source_repository import set_repositories_mode

os.environ["VISIONFLOW_USE_DEV_REPOSITORIES"] = "1"
os.environ["VISIONFLOW_ALLOW_INSECURE_DB"] = "true"
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/testdb?sslmode=require")

@pytest.fixture(autouse=True)
def ensure_dev_repositories_for_retrieval(monkeypatch, request):
    if "alembic_postgres" in request.node.nodeid:
        monkeypatch.delenv("VISIONFLOW_USE_DEV_REPOSITORIES", raising=False)
        return
    monkeypatch.setenv("VISIONFLOW_USE_DEV_REPOSITORIES", "1")
    monkeypatch.setenv("VISIONFLOW_ALLOW_INSECURE_DB", "true")
    set_repositories_mode(use_dev=True)
