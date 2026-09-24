"""Run render regressions without touching saved production runs or .env.

Usage: python scripts/validate_remote_render.py
Requires ffmpeg/ffprobe on PATH and VISIONFLOW_TEST_POSTGRES_URL for real PG tests.
Output artifacts are retained in a fresh .media_cache/remote-validation-* directory.
"""
from __future__ import annotations

import importlib
import builtins
import os
from pathlib import Path
import socket
import sys
import tempfile


def main():
    backend = Path(__file__).resolve().parents[1]
    os.chdir(backend)
    sys.path[:0] = [str(backend), str(backend / "services" / "control-plane")]
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["DATABASE_URL"] = "postgresql+psycopg://unused@127.0.0.1:1/unused"
    os.environ.pop("MIGRATION_DATABASE_URL", None)
    os.environ["VISIONFLOW_ALLOW_INSECURE_DB"] = "true"
    os.environ["VISIONFLOW_USE_DEV_REPOSITORIES"] = "1"
    os.environ["VISIONFLOW_ALLOW_TEST_TTS"] = "1"
    os.environ.pop("VISIONFLOW_RENDER_POLICY", None)
    os.environ["VISIONFLOW_RENDER_TARGET"] = "LOCAL_DIRECT"
    os.environ["VISIONFLOW_RENDER_JOB_BACKEND"] = "postgres"
    for key in list(os.environ):
        if any(part in key for part in ("API_KEY", "SECRET", "WORKER_TOKEN")):
            os.environ.pop(key, None)
    import dotenv
    dotenv.load_dotenv = lambda *args, **kwargs: False
    root = Path(tempfile.mkdtemp(prefix="remote-validation-", dir=backend / ".media_cache"))
    tempfile.tempdir = str(root)
    os.environ["TEMP"] = os.environ["TMP"] = str(root)
    modules = {name: importlib.import_module("production." + name) for name in (
        "repositories.run_repository", "render_handoff", "tts_service", "human_review", "pilot_learning", "source_ingest")}
    modules["repositories.run_repository"].STORAGE_DIR = root / "runs"
    modules["repositories.run_repository"].STORAGE_DIR.mkdir()
    modules["repositories.run_repository"].DevelopmentRunRepository._runs = {}
    modules["render_handoff"].render_handoff.exports_dir = root / "exports"
    modules["tts_service"].CACHE_DIR = root / "tts"
    modules["tts_service"].CACHE_DIR.mkdir()
    modules["human_review"].human_review_service.storage_dir = root / "reviews"
    modules["human_review"].human_review_service.storage_dir.mkdir()
    modules["source_ingest"].MEDIA_CACHE_DIR = root / "ingest"
    modules["source_ingest"].MEDIA_CACHE_DIR.mkdir()
    # Existing singletons may have loaded local fixture/catalog state at import time.
    # Empty and relocate them; never mutate the repository's saved source library.
    from production.repositories.source_repository import get_source_repository, get_scene_repository, get_embedding_repository
    for name, repository, attribute in (
        ('sources', get_source_repository(), '_sources'), ('scenes', get_scene_repository(), '_scenes'),
        ('embeddings', get_embedding_repository(), '_entries'),
    ):
        repository.storage_dir = root / name
        repository.storage_dir.mkdir()
        setattr(repository, attribute, {})
    import production.asset_resolver as resolver_module
    resolver_module.CACHE_FILE_PATH = root / 'asset-cache.json'
    resolver_module.asset_resolver.stock_adapter._cache = {}

    redirects = {
        str(Path("d:/VisionFlow/.media_cache/test_fixtures")).lower(): root / "phase6-fixtures",
        str(Path("d:/VisionFlow/.media_cache/test_fixtures_p7")).lower(): root / "phase7-fixtures",
        str(backend / "scripts" / "pilot_production_report.json").lower(): root / "pilot-report.json",
    }
    def redirected_path(*parts):
        value = Path(*parts)
        return redirects.get(str(value).lower(), value)
    modules["pilot_learning"].Path = redirected_path
    def isolated_report_open(file, *args, **kwargs):
        if Path(file).name == "pilot_production_report.json":
            file = root / "pilot-report.json"
        return builtins.open(file, *args, **kwargs)
    modules["pilot_learning"].open = isolated_report_open

    original_connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "localhost", "::1"):
            allowed_tts = os.getenv('VISIONFLOW_TEST_LIVE_TTS') == '1' and address[1] == 443 and address[0] in {
                item[4][0] for item in socket.getaddrinfo('speech.platform.bing.com', 443)
            }
            if not allowed_tts:
                raise RuntimeError("Validation blocks external network access")
        return original_connect(sock, address)
    socket.socket.connect = local_connect

    class Isolation:
        def pytest_collection_modifyitems(self, items):
            for item in items:
                if item.module.__name__ in ("test_phase6_render_qc", "test_phase7_production_stabilization"):
                    item.module.Path = redirected_path

    import pytest
    print(f"Isolated validation artifacts: {root}", flush=True)
    args = ["-q", "-p", "no:cacheprovider", "--basetemp", str(root / "pytest"),
            "tests/test_phase6_render_qc.py", "tests/test_phase7_production_stabilization.py",
            "tests/test_pilot_learning_loop.py", "tests/test_production_api_runtime.py",
            "tests/test_remote_render_repository.py", "tests/test_remote_worker.py", "tests/test_remote_worker_reliability.py", "tests/test_remote_render_integration.py", "tests/test_review_integration.py"]
    return pytest.main(args + ["--tb=short"] + sys.argv[1:], plugins=[Isolation()])


if __name__ == "__main__":
    raise SystemExit(main())
