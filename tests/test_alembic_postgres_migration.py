"""
PostgreSQL Migration & Rollback Integration Test Suite (Section 3)
Tests:
- Applies Alembic migration 0019_auto_production_scene_library to PostgreSQL.
- Verifies tables (source_assets, source_scenes, scene_embeddings), indexes, and FK constraints.
- Tests downgrade (rollback) cleanly.
- Re-upgrades to head to leave PostgreSQL ready for runtime.
"""

import os
import sys
from pathlib import Path
import dotenv
import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

CONTROL_PLANE = BACKEND_ROOT / "services" / "control-plane"
if str(CONTROL_PLANE) not in sys.path:
    sys.path.insert(0, str(CONTROL_PLANE))

dotenv.load_dotenv(BACKEND_ROOT / ".env")

# Ensure MIGRATION_DATABASE_URL is set for Alembic env.py
if not os.getenv("MIGRATION_DATABASE_URL"):
    os.environ["MIGRATION_DATABASE_URL"] = os.getenv("DIRECT_DATABASE_URL") or os.getenv("DATABASE_URL") or ""

from alembic import command
from alembic.config import Config
import psycopg



def get_alembic_config() -> Config:
    ini_path = CONTROL_PLANE / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(CONTROL_PLANE / "alembic"))
    db_url = os.getenv("DIRECT_DATABASE_URL") or os.getenv("DATABASE_URL")
    if db_url.startswith("postgresql://"):
        db_url = f"postgresql+psycopg://{db_url.removeprefix('postgresql://')}"
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def test_postgres_migration_and_rollback():
    db_url = os.getenv("DIRECT_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        pytest.skip("DATABASE_URL not configured")

    cfg = get_alembic_config()

    print("\n[POSTGRESQL MIGRATION] 1. Upgrade to 0020_retrieval_hardening...")
    command.upgrade(cfg, "0020_retrieval_hardening")


    # Connect with psycopg to verify table metadata directly in PostgreSQL
    # Psycopg accepts standard postgresql:// URL
    raw_url = os.getenv("DIRECT_DATABASE_URL") or os.getenv("DATABASE_URL")
    conn = psycopg.connect(raw_url)
    conn.autocommit = True
    cur = conn.cursor()

    try:
        print("[POSTGRESQL MIGRATION] 2. Verifying tables exist in information_schema...")
        cur.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('source_assets', 'source_scenes', 'scene_embeddings');
        """)
        tables = {row[0] for row in cur.fetchall()}
        assert "source_assets" in tables, "source_assets table not found in PostgreSQL"
        assert "source_scenes" in tables, "source_scenes table not found in PostgreSQL"
        assert "scene_embeddings" in tables, "scene_embeddings table not found in PostgreSQL"
        print(f"  -> Verified 3 tables in PostgreSQL: {tables}")

        print("[POSTGRESQL MIGRATION] 2b. Verifying 0020 hardening columns...")
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'source_assets' AND column_name = 'fast_fingerprint'")
        assert len(cur.fetchall()) == 1, "fast_fingerprint column missing in source_assets"
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'source_scenes' AND column_name = 'visual_fingerprint'")
        assert len(cur.fetchall()) == 1, "visual_fingerprint column missing in source_scenes"
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'scene_embeddings' AND column_name IN ('provider', 'model', 'embedding_version')")
        found_cols = {r[0] for r in cur.fetchall()}
        assert {"provider", "model", "embedding_version"}.issubset(found_cols), f"Missing versioning columns in scene_embeddings: {found_cols}"
        print("  -> Verified 0020 hardening columns successfully!")

        print("[POSTGRESQL MIGRATION] 3. Verifying indexes...")
        cur.execute("""
            SELECT indexname FROM pg_indexes 
            WHERE tablename IN ('source_assets', 'source_scenes', 'scene_embeddings');
        """)
        indexes = {row[0] for row in cur.fetchall()}
        assert "ix_source_assets_fingerprint" in indexes, "ix_source_assets_fingerprint index missing"
        assert "ix_source_scenes_source_id" in indexes, "ix_source_scenes_source_id index missing"
        assert "ix_source_scenes_fingerprint" in indexes, "ix_source_scenes_fingerprint index missing"
        assert "ix_scene_embeddings_scene_id" in indexes, "ix_scene_embeddings_scene_id index missing"
        print(f"  -> Verified indexes: {indexes}")

        print("[POSTGRESQL MIGRATION] 4. Verifying foreign key constraint...")
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute("""
                INSERT INTO source_scenes (id, source_id, start_sec, end_sec, duration_sec, fingerprint)
                VALUES ('scn_bad_01', 'non_existent_source', 0.0, 3.0, 3.0, 'fp_bad');
            """)
        print("  -> FK constraint blocked orphan scene successfully.")

        print("[POSTGRESQL MIGRATION] 5. Verifying downgrade / rollback...")
        command.downgrade(cfg, "0018_voice_system")
        cur.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('source_assets', 'source_scenes', 'scene_embeddings');
        """)
        remaining = [row[0] for row in cur.fetchall()]
        assert len(remaining) == 0, f"Tables should be dropped after downgrade, found {remaining}"
        print("  -> Rollback verified: tables dropped cleanly.")

        print("[POSTGRESQL MIGRATION] 6. Re-upgrade to leave database at head...")
        command.upgrade(cfg, "0020_retrieval_hardening")
        print("  -> PostgreSQL migration re-applied successfully!")


    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    test_postgres_migration_and_rollback()
