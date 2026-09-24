"""
Database Migration & Schema Verification Test (Mục 5)
Proves that 001_auto_production.sql creates valid relational tables,
indexes, and foreign key constraints on an isolated test database.
"""

import sqlite3
import uuid
from pathlib import Path

SQL_PATH = Path(__file__).resolve().parent.parent / "db" / "migrations" / "001_auto_production.sql"
TEST_DB_PATH = Path(__file__).resolve().parent.parent / "test_migration_verification.db"


def test_migration():
    print("[MIGRATION TEST] 1. Initializing isolated test database...")
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    conn = sqlite3.connect(TEST_DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    cursor = conn.cursor()

    print("[MIGRATION TEST] 2. Reading and applying 001_auto_production.sql...")
    assert SQL_PATH.exists(), f"Migration file not found at {SQL_PATH}"
    with open(SQL_PATH, "r", encoding="utf-8") as f:
        sql_content = f.read()

    cursor.executescript(sql_content)
    conn.commit()

    print("[MIGRATION TEST] 3. Verifying 6 core tables existence...")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}
    required_tables = {
        "production_runs",
        "production_stage_runs",
        "source_assets",
        "source_scenes",
        "editor_plans",
        "quality_reports",
    }
    for t in required_tables:
        assert t in tables, f"Missing required table: {t}"
    print(f"  -> All 6 tables verified: {sorted(required_tables)}")

    print("[MIGRATION TEST] 4. Verifying indexes...")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index';")
    indexes = {row[0] for row in cursor.fetchall()}
    required_indexes = {
        "idx_stage_run",
        "idx_source_fingerprint",
        "idx_scene_source",
        "idx_scene_fingerprint",
    }
    for idx in required_indexes:
        assert idx in indexes, f"Missing required index: {idx}"
    print(f"  -> All 4 indexes verified: {sorted(required_indexes)}")

    print("[MIGRATION TEST] 5. Verifying Foreign Key Enforcement...")
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    
    # Attempting to insert child stage run with non-existent run_id must fail FK
    fk_failed = False
    try:
        cursor.execute(
            """INSERT INTO production_stage_runs (id, run_id, stage_name, status)
               VALUES (?, ?, ?, ?)""",
            (f"stg_{uuid.uuid4().hex[:8]}", "non_existent_run_id", "input_normalization", "PENDING")
        )
        conn.commit()
    except sqlite3.IntegrityError:
        fk_failed = True
    assert fk_failed, "Foreign Key violation was not enforced!"
    print("  -> Foreign Key constraint verified (blocked invalid parent reference)!")

    print("[MIGRATION TEST] 6. Testing CRUD operations (Insert, Read, Update)...")
    cursor.execute(
        """INSERT INTO production_runs (id, video_project_id, channel_profile_id, status, mode, request_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (run_id, "proj_001", "profile_vn", "CREATED", "auto", '{"instruction": "Test video"}')
    )
    conn.commit()

    # Read back
    cursor.execute("SELECT status, mode FROM production_runs WHERE id = ?", (run_id,))
    row = cursor.fetchone()
    assert row is not None and row[0] == "CREATED" and row[1] == "auto"

    # Insert stage run
    stg_id = f"stg_{uuid.uuid4().hex[:8]}"
    cursor.execute(
        """INSERT INTO production_stage_runs (id, run_id, stage_name, status)
           VALUES (?, ?, ?, ?)""",
        (stg_id, run_id, "input_normalization", "COMPLETED")
    )
    conn.commit()

    # Update run
    cursor.execute(
        """UPDATE production_runs SET status = ?, quality_score = ? WHERE id = ?""",
        ("FOUNDATION_READY", 0.95, run_id)
    )
    conn.commit()

    cursor.execute("SELECT status, quality_score FROM production_runs WHERE id = ?", (run_id,))
    row = cursor.fetchone()
    assert row[0] == "FOUNDATION_READY" and abs(row[1] - 0.95) < 0.001
    print("  -> CRUD operations on production_runs verified successfully!")

    print("[MIGRATION TEST] 7. Cleanup test database...")
    conn.close()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    print("[MIGRATION TEST] [SUCCESS] All migration verification checks passed!")


if __name__ == "__main__":
    test_migration()
