-- VisionFlow Auto Production — initial relational schema
-- Adapt types/index syntax to SQLite / MySQL / PostgreSQL

CREATE TABLE IF NOT EXISTS production_runs (
    id VARCHAR(64) PRIMARY KEY,
    video_project_id VARCHAR(64),
    channel_profile_id VARCHAR(64),
    status VARCHAR(32) NOT NULL,
    mode VARCHAR(32) NOT NULL,
    request_json TEXT NOT NULL,
    quality_score REAL,
    blocker_count INTEGER DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS production_stage_runs (
    id VARCHAR(64) PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL,
    stage_name VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    input_hash VARCHAR(128),
    output_version VARCHAR(32),
    model_name VARCHAR(64),
    duration_ms INTEGER,
    cost_usd REAL DEFAULT 0,
    error_code VARCHAR(64),
    output_json TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES production_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_stage_run
ON production_stage_runs(run_id, stage_name);

CREATE TABLE IF NOT EXISTS source_assets (
    id VARCHAR(64) PRIMARY KEY,
    run_id VARCHAR(64),
    source_type VARCHAR(32) NOT NULL,
    uri TEXT,
    local_ref TEXT,
    fingerprint VARCHAR(128),
    rights_state VARCHAR(32) NOT NULL,
    watermark_state VARCHAR(32),
    metadata_json TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_source_fingerprint
ON source_assets(fingerprint);

CREATE TABLE IF NOT EXISTS source_scenes (
    id VARCHAR(64) PRIMARY KEY,
    source_id VARCHAR(64) NOT NULL,
    start_sec REAL NOT NULL,
    end_sec REAL NOT NULL,
    fingerprint VARCHAR(128) NOT NULL,
    description TEXT,
    transcript TEXT,
    entities_json TEXT,
    actions_json TEXT,
    shot_type VARCHAR(64),
    motion_score REAL,
    technical_quality_score REAL,
    embedding_ref VARCHAR(128),
    analysis_version VARCHAR(32),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_id) REFERENCES source_assets(id)
);

CREATE INDEX IF NOT EXISTS idx_scene_source
ON source_scenes(source_id);

CREATE INDEX IF NOT EXISTS idx_scene_fingerprint
ON source_scenes(fingerprint);

CREATE TABLE IF NOT EXISTS editor_plans (
    id VARCHAR(64) PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL,
    script_version VARCHAR(32),
    plan_json TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES production_runs(id)
);

CREATE TABLE IF NOT EXISTS quality_reports (
    id VARCHAR(64) PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL,
    stage_name VARCHAR(64) NOT NULL,
    overall_status VARCHAR(32) NOT NULL,
    score REAL,
    blocker_count INTEGER DEFAULT 0,
    warning_count INTEGER DEFAULT 0,
    report_json TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES production_runs(id)
);
