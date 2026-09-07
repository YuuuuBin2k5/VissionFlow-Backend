"""Real PostgreSQL queue tests in a unique schema, never in deployment tables.

Set VISIONFLOW_TEST_POSTGRES_URL to an explicitly selected localhost test
database. Other remote-render integration suites can import remote_pg_engine.
"""
from __future__ import annotations

import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

CONTROL_PLANE = Path(__file__).resolve().parents[1] / "services" / "control-plane"
sys.path.insert(0, str(CONTROL_PLANE))

from app.core.config import ConfigurationError
from app.infrastructure.models import RenderJob, RenderWorker
from app.infrastructure.render_job_repository import (
    PostgresRenderJobRepository,
    PostgresRenderWorkerRepository,
    get_render_job_repository,
)


@pytest.fixture
def remote_pg_engine():
    url = os.getenv("VISIONFLOW_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set VISIONFLOW_TEST_POSTGRES_URL to run real PostgreSQL tests")
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql" or parsed.host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("Remote render tests require an explicitly configured localhost PostgreSQL database")
    schema = "vf_render_test_" + uuid.uuid4().hex
    raw_engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    with raw_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = raw_engine.execution_options(schema_translate_map={None: schema})
    try:
        RenderWorker.metadata.create_all(engine, tables=[RenderWorker.__table__, RenderJob.__table__])
        yield engine
    finally:
        # Only this fixture's random identifier can reach the cleanup statement.
        with raw_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        raw_engine.dispose()


def register(session: Session, worker_id: str, *, capacity: int = 1):
    return PostgresRenderWorkerRepository(session).register_worker(
        worker_id=worker_id, worker_type="PERSONAL_LOCAL", platform="windows",
        renderer_version="canonical-v1", ffmpeg_version="test-real-pg",
        capabilities={"canonical_render": True}, max_concurrent_jobs=capacity,
    )


def create(session: Session, *, key: str = "one", max_attempts: int = 3):
    return PostgresRenderJobRepository(session).create_job(
        run_id="run_" + key, spec={"manifest": {"artifacts": []}, "run_snapshot": {"run_id": "run_" + key}},
        input_hash="a" * 64, idempotency_key=key, max_attempts=max_attempts,
    )


def test_create_reload_claim_heartbeat_complete_and_durability(remote_pg_engine):
    with Session(remote_pg_engine) as session:
        register(session, "desktop-a")
        job_id = create(session).id
    # Discard pooled connections and the producing session before loading.
    remote_pg_engine.dispose()
    with Session(remote_pg_engine) as session:
        repo = get_render_job_repository(session)
        assert repo.get_job(str(job_id)).status == "WAITING_FOR_WORKER"
        assert repo.get_job_by_idempotency_key("one").id == job_id
        job = repo.claim_next_job("desktop-a")
        assert job.id == job_id and job.attempt == 1
        prior_lease = job.lease_expires_at
        repo.heartbeat_job(job_id, "desktop-a", lease_seconds=240, attempt=1)
        assert job.lease_expires_at > prior_lease
        repo.update_progress(job_id, "desktop-a", "DOWNLOADING", attempt=1)
        repo.update_progress(job_id, "desktop-a", "RENDERING", attempt=1)
        repo.update_progress(job_id, "desktop-a", "UPLOADING", attempt=1)
        result = repo.complete_job(job_id, "desktop-a", "runs/run_one/final.mp4", attempt=1)
        assert result.status == "COMPLETED" and result.completed_at is not None
        assert result.lease_expires_at is None
        assert repo.complete_job(job_id, "desktop-a", result.output_artifact_ref, attempt=1).status == "COMPLETED"
        with pytest.raises(ValueError, match="different artifact"):
            repo.complete_job(job_id, "desktop-a", "other.mp4", attempt=1)
    with Session(remote_pg_engine) as session:
        assert PostgresRenderJobRepository(session).get_job(job_id).output_artifact_ref == "runs/run_one/final.mp4"


def test_two_concurrent_claims_one_job_exactly_one_worker(remote_pg_engine):
    with Session(remote_pg_engine) as session:
        register(session, "desktop-a")
        register(session, "desktop-b")
        job_id = create(session).id
    barrier = Barrier(2)

    def claim(worker_id: str):
        with Session(remote_pg_engine) as session:
            barrier.wait(timeout=10)
            job = PostgresRenderJobRepository(session).claim_next_job(worker_id)
            return (str(job.id), job.claimed_by_worker_id) if job else None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ["desktop-a", "desktop-b"]))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1 and winners[0][0] == str(job_id)
    with Session(remote_pg_engine) as session:
        job = PostgresRenderJobRepository(session).get_job(job_id)
        assert job.attempt == 1 and job.claimed_by_worker_id == winners[0][1]


def test_locked_row_is_skipped_without_waiting(remote_pg_engine):
    with Session(remote_pg_engine) as session:
        register(session, "desktop-a")
        job_id = create(session).id
    with Session(remote_pg_engine) as locking_session:
        locking_session.scalar(select(RenderJob).where(RenderJob.id == job_id).with_for_update())
        with Session(remote_pg_engine) as claimant:
            # A blocking FOR UPDATE would fail this bounded statement timeout.
            claimant.execute(text("SET LOCAL statement_timeout = '1500ms'"))
            assert PostgresRenderJobRepository(claimant).claim_next_job("desktop-a") is None


def test_concurrent_claims_preserve_worker_capacity(remote_pg_engine):
    with Session(remote_pg_engine) as session:
        register(session, "desktop-a", capacity=1)
        create(session, key="one")
        create(session, key="two")
    barrier = Barrier(2)

    def claim(_):
        with Session(remote_pg_engine) as session:
            barrier.wait(timeout=10)
            job = PostgresRenderJobRepository(session).claim_next_job("desktop-a")
            return str(job.id) if job else None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, range(2)))
    assert sum(result is not None for result in results) == 1


def test_concurrent_create_is_idempotent(remote_pg_engine):
    barrier = Barrier(2)

    def producer(_):
        with Session(remote_pg_engine) as session:
            barrier.wait(timeout=10)
            return str(create(session).id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(producer, range(2)))
    assert results[0] == results[1]
    with Session(remote_pg_engine) as session:
        assert session.scalar(select(func.count()).select_from(RenderJob)) == 1
        with pytest.raises(ValueError, match="different input"):
            PostgresRenderJobRepository(session).create_job(
                run_id="another", spec={}, input_hash="b" * 64, idempotency_key="one",
            )


def test_expired_lease_cannot_revive_and_recovers_to_another_worker(remote_pg_engine):
    with Session(remote_pg_engine) as session:
        register(session, "desktop-a")
        register(session, "desktop-b")
        job_id = create(session).id
        repo = PostgresRenderJobRepository(session)
        job = repo.claim_next_job("desktop-a")
        job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
        with pytest.raises(PermissionError, match="expired"):
            repo.heartbeat_job(job_id, "desktop-a", attempt=1)
        session.rollback()
        assert repo.release_expired_jobs() == 1
        assert repo.release_expired_jobs() == 0
        recovered = repo.claim_next_job("desktop-b")
        assert recovered.id == job_id and recovered.attempt == 2
        with pytest.raises(PermissionError):
            repo.complete_job(job_id, "desktop-a", "stale.mp4", attempt=1)


def test_attempt_fence_for_same_restarted_worker_and_retry_limit(remote_pg_engine):
    with Session(remote_pg_engine) as session:
        register(session, "desktop-a")
        job_id = create(session, max_attempts=2).id
        repo = PostgresRenderJobRepository(session)
        repo.claim_next_job("desktop-a")
        job = repo.fail_job(job_id, "desktop-a", "UPLOAD_FAILED", "retry", True, attempt=1)
        assert job.status == "RETRYING" and job.claimed_by_worker_id is None
        repo.claim_next_job("desktop-a")
        for operation in (
            lambda: repo.heartbeat_job(job_id, "desktop-a", attempt=1),
            lambda: repo.update_progress(job_id, "desktop-a", "RENDERING", attempt=1),
            lambda: repo.fail_job(job_id, "desktop-a", "old", "old", True, attempt=1),
            lambda: repo.complete_job(job_id, "desktop-a", "old.mp4", attempt=1),
        ):
            with pytest.raises(PermissionError, match="attempt"):
                operation()
            session.rollback()
        failed = repo.fail_job(job_id, "desktop-a", "RENDER_FAILED", "final", True, attempt=2)
        assert failed.status == "FAILED" and failed.failed_at is not None
        assert repo.claim_next_job("desktop-a") is None


def test_progress_allowlist_and_foreign_worker_are_rejected(remote_pg_engine):
    with Session(remote_pg_engine) as session:
        register(session, "desktop-a")
        job_id = create(session).id
        repo = PostgresRenderJobRepository(session)
        repo.claim_next_job("desktop-a")
        with pytest.raises(PermissionError):
            repo.update_progress(job_id, "desktop-b", "DOWNLOADING", attempt=1)
        session.rollback()
        with pytest.raises(ValueError, match="Unsupported"):
            repo.update_progress(job_id, "desktop-a", "COMPLETED", attempt=1)
        repo.update_progress(job_id, "desktop-a", "RENDERING", attempt=1)
        with pytest.raises(ValueError, match="backwards"):
            repo.update_progress(job_id, "desktop-a", "DOWNLOADING", attempt=1)


def test_expired_final_attempt_and_non_retryable_failures_are_terminal(remote_pg_engine):
    with Session(remote_pg_engine) as session:
        register(session, "desktop-a")
        job_id = create(session, max_attempts=1).id
        repo = PostgresRenderJobRepository(session)
        job = repo.claim_next_job("desktop-a")
        job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
        assert repo.release_expired_jobs() == 1
        failed = repo.get_job(job_id)
        assert failed.status == "FAILED" and failed.failed_at is not None
        assert failed.error_code == "WORKER_LEASE_EXPIRED"
        assert repo.claim_next_job("desktop-a") is None
        second_id = create(session, key="nonretryable").id
        repo.claim_next_job("desktop-a")
        failed = repo.fail_job(
            second_id, "desktop-a", "ASSET_CHECKSUM_MISMATCH", "invalid asset", False, attempt=1,
        )
        assert failed.status == "FAILED" and not failed.retryable
        assert repo.claim_next_job("desktop-a") is None


def test_completion_lock_leaves_commit_to_caller(remote_pg_engine):
    with Session(remote_pg_engine) as session:
        register(session, "desktop-a")
        job_id = create(session).id
        repo = PostgresRenderJobRepository(session)
        repo.claim_next_job("desktop-a")
        job = repo.locked_owned_job(job_id, "desktop-a", 1)
        job.status = "COMPLETED"
        job.render_spec_json = {**job.render_spec_json, "completion": {"checksum": "a" * 64}}
        session.rollback()
    with Session(remote_pg_engine) as session:
        job = PostgresRenderJobRepository(session).get_job(job_id)
        assert job.status == "CLAIMED" and "completion" not in job.render_spec_json


def test_worker_status_heartbeat_and_claim_registration(remote_pg_engine):
    with Session(remote_pg_engine) as session:
        repo = PostgresRenderJobRepository(session)
        with pytest.raises(PermissionError):
            repo.claim_next_job("unregistered")
        register(session, "desktop-a")
        create(session)
        repo.claim_next_job("desktop-a")
        workers = PostgresRenderWorkerRepository(session)
        status = workers.list_active_workers()
        assert status[0]["active_jobs"] == 1 and status[0]["capacity"] == 1
        assert set(status[0]) == {"worker_id", "status", "last_heartbeat_at", "active_jobs", "capacity"}
        worker = workers.get_worker("desktop-a")
        worker.last_heartbeat_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        session.commit()
        assert workers.list_active_workers() == []
        assert workers.list_workers()[0]["status"] == "OFFLINE"
        workers.heartbeat_worker("desktop-a")
        assert workers.list_active_workers()[0]["status"] == "ONLINE"


def test_factory_rejects_in_memory_for_remote_service(remote_pg_engine, monkeypatch):
    monkeypatch.setenv("VISIONFLOW_RENDER_JOB_BACKEND", "in_memory")
    with Session(remote_pg_engine) as session:
        with pytest.raises(ConfigurationError, match="postgres"):
            get_render_job_repository(session)
