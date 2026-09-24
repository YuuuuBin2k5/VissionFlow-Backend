BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001_initial_visionflow_v1

CREATE TABLE organizations (
    id UUID NOT NULL, 
    slug VARCHAR(80) NOT NULL, 
    name VARCHAR(160) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (slug)
);

CREATE TABLE users (
    id UUID NOT NULL, 
    identity_subject VARCHAR(512) NOT NULL, 
    email VARCHAR(320), 
    display_name VARCHAR(160), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (identity_subject)
);

CREATE TABLE organization_memberships (
    id UUID NOT NULL, 
    organization_id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    role VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_organization_membership UNIQUE (organization_id, user_id), 
    FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE, 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_organization_memberships_user ON organization_memberships (user_id);

CREATE TABLE video_projects (
    id UUID NOT NULL, 
    organization_id UUID NOT NULL, 
    title VARCHAR(240) NOT NULL, 
    brief TEXT NOT NULL, 
    format_profile VARCHAR(64) DEFAULT 'short_vertical' NOT NULL, 
    timezone VARCHAR(64) DEFAULT 'Asia/Bangkok' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE RESTRICT
);

CREATE INDEX ix_video_projects_organization_created ON video_projects (organization_id, created_at);

CREATE TABLE workflow_runs (
    id UUID NOT NULL, 
    project_id UUID NOT NULL, 
    state VARCHAR(32) NOT NULL, 
    idempotency_key VARCHAR(128) NOT NULL, 
    prompt_manifest JSONB DEFAULT '{}'::jsonb NOT NULL, 
    input_payload JSONB DEFAULT '{}'::jsonb NOT NULL, 
    failure_code VARCHAR(96), 
    failure_detail TEXT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(project_id) REFERENCES video_projects (id) ON DELETE CASCADE, 
    UNIQUE (idempotency_key)
);

CREATE INDEX ix_workflow_runs_project_created ON workflow_runs (project_id, created_at);

CREATE INDEX ix_workflow_runs_state_created ON workflow_runs (state, created_at);

CREATE TABLE workflow_steps (
    id UUID NOT NULL, 
    workflow_run_id UUID NOT NULL, 
    step_key VARCHAR(64) NOT NULL, 
    state VARCHAR(32) NOT NULL, 
    attempt_count INTEGER DEFAULT '0' NOT NULL, 
    input_payload JSONB DEFAULT '{}'::jsonb NOT NULL, 
    output_payload JSONB, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_workflow_step_key UNIQUE (workflow_run_id, step_key), 
    FOREIGN KEY(workflow_run_id) REFERENCES workflow_runs (id) ON DELETE CASCADE
);

CREATE INDEX ix_workflow_steps_run_state ON workflow_steps (workflow_run_id, state);

CREATE TABLE prompt_templates (
    id UUID NOT NULL, 
    organization_id UUID NOT NULL, 
    prompt_key VARCHAR(100) NOT NULL, 
    name VARCHAR(160) NOT NULL, 
    description TEXT NOT NULL, 
    production_version INTEGER, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_prompt_template_key UNIQUE (organization_id, prompt_key), 
    FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE
);

CREATE TABLE prompt_versions (
    id UUID NOT NULL, 
    prompt_template_id UUID NOT NULL, 
    version INTEGER NOT NULL, 
    content TEXT NOT NULL, 
    config JSONB DEFAULT '{}'::jsonb NOT NULL, 
    change_note VARCHAR(500), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_prompt_version UNIQUE (prompt_template_id, version), 
    FOREIGN KEY(prompt_template_id) REFERENCES prompt_templates (id) ON DELETE CASCADE
);

CREATE TABLE prompt_audit_events (
    id UUID NOT NULL, 
    organization_id UUID NOT NULL, 
    prompt_template_id UUID NOT NULL, 
    action VARCHAR(64) NOT NULL, 
    actor_subject VARCHAR(512) NOT NULL, 
    payload JSONB DEFAULT '{}'::jsonb NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE, 
    FOREIGN KEY(prompt_template_id) REFERENCES prompt_templates (id) ON DELETE CASCADE
);

CREATE INDEX ix_prompt_audit_events_template_created ON prompt_audit_events (prompt_template_id, created_at);

CREATE TABLE media_assets (
    id UUID NOT NULL, 
    organization_id UUID NOT NULL, 
    workflow_run_id UUID, 
    object_key VARCHAR(1024) NOT NULL, 
    media_kind VARCHAR(48) NOT NULL, 
    content_type VARCHAR(128) NOT NULL, 
    byte_size BIGINT NOT NULL, 
    checksum_sha256 VARCHAR(64) NOT NULL, 
    metadata_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE RESTRICT, 
    FOREIGN KEY(workflow_run_id) REFERENCES workflow_runs (id) ON DELETE SET NULL, 
    UNIQUE (object_key)
);

CREATE INDEX ix_media_assets_run_kind ON media_assets (workflow_run_id, media_kind);

CREATE TABLE publish_approvals (
    id UUID NOT NULL, 
    workflow_run_id UUID NOT NULL, 
    export_asset_id UUID NOT NULL, 
    decision VARCHAR(24) NOT NULL, 
    reviewer_subject VARCHAR(255) NOT NULL, 
    note TEXT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (workflow_run_id), 
    FOREIGN KEY(workflow_run_id) REFERENCES workflow_runs (id) ON DELETE CASCADE, 
    FOREIGN KEY(export_asset_id) REFERENCES media_assets (id) ON DELETE RESTRICT
);

CREATE TABLE outbox_events (
    id UUID NOT NULL, 
    aggregate_type VARCHAR(64) NOT NULL, 
    aggregate_id UUID NOT NULL, 
    event_type VARCHAR(160) NOT NULL, 
    payload JSONB NOT NULL, 
    trace_id VARCHAR(64) NOT NULL, 
    published_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_outbox_events_pending ON outbox_events (created_at) WHERE published_at IS NULL;

INSERT INTO alembic_version (version_num) VALUES ('0001_initial_visionflow_v1') RETURNING alembic_version.version_num;

-- Running upgrade 0001_initial_visionflow_v1 -> 0002_local_auth_foundation

CREATE TABLE auth_users (
    id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    email VARCHAR(320) NOT NULL, 
    password_hash TEXT NOT NULL, 
    email_verified_at TIMESTAMP WITH TIME ZONE, 
    password_changed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (user_id), 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    UNIQUE (email)
);

CREATE TABLE auth_sessions (
    id UUID NOT NULL, 
    auth_user_id UUID NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    revoked_at TIMESTAMP WITH TIME ZONE, 
    revoke_reason VARCHAR(96), 
    last_seen_at TIMESTAMP WITH TIME ZONE, 
    ip_address VARCHAR(64), 
    user_agent VARCHAR(512), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(auth_user_id) REFERENCES auth_users (id) ON DELETE CASCADE
);

CREATE INDEX ix_auth_sessions_user_active ON auth_sessions (auth_user_id, expires_at);

CREATE TABLE auth_refresh_tokens (
    id UUID NOT NULL, 
    session_id UUID NOT NULL, 
    token_digest VARCHAR(64) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    consumed_at TIMESTAMP WITH TIME ZONE, 
    revoked_at TIMESTAMP WITH TIME ZONE, 
    replaced_by_id UUID, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(session_id) REFERENCES auth_sessions (id) ON DELETE CASCADE, 
    UNIQUE (token_digest), 
    FOREIGN KEY(replaced_by_id) REFERENCES auth_refresh_tokens (id) ON DELETE SET NULL
);

CREATE INDEX ix_auth_refresh_tokens_session_expiry ON auth_refresh_tokens (session_id, expires_at);

CREATE TABLE auth_audit_events (
    id UUID NOT NULL, 
    auth_user_id UUID, 
    event_type VARCHAR(80) NOT NULL, 
    outcome VARCHAR(24) NOT NULL, 
    ip_address VARCHAR(64), 
    user_agent VARCHAR(512), 
    metadata_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(auth_user_id) REFERENCES auth_users (id) ON DELETE SET NULL
);

CREATE INDEX ix_auth_audit_events_user_created ON auth_audit_events (auth_user_id, created_at);

UPDATE alembic_version SET version_num='0002_local_auth_foundation' WHERE alembic_version.version_num = '0001_initial_visionflow_v1';

-- Running upgrade 0002_local_auth_foundation -> 0003_creative_documents

CREATE TABLE creative_documents (
    id UUID NOT NULL, 
    workflow_run_id UUID NOT NULL, 
    revision INTEGER DEFAULT '0' NOT NULL, 
    active_version_id UUID, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (workflow_run_id), 
    FOREIGN KEY(workflow_run_id) REFERENCES workflow_runs (id) ON DELETE CASCADE
);

CREATE TABLE creative_document_versions (
    id UUID NOT NULL, 
    creative_document_id UUID NOT NULL, 
    version INTEGER NOT NULL, 
    state VARCHAR(24) DEFAULT 'draft' NOT NULL, 
    script TEXT NOT NULL, 
    source VARCHAR(24) DEFAULT 'operator' NOT NULL, 
    created_by_subject VARCHAR(512) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_creative_document_version UNIQUE (creative_document_id, version), 
    FOREIGN KEY(creative_document_id) REFERENCES creative_documents (id) ON DELETE CASCADE
);

CREATE TABLE creative_scenes (
    id UUID NOT NULL, 
    creative_document_version_id UUID NOT NULL, 
    position INTEGER NOT NULL, 
    narration TEXT NOT NULL, 
    visual_prompt TEXT NOT NULL, 
    duration_seconds INTEGER NOT NULL, 
    transition VARCHAR(48) DEFAULT 'cut' NOT NULL, 
    caption TEXT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_creative_scene_position UNIQUE (creative_document_version_id, position), 
    FOREIGN KEY(creative_document_version_id) REFERENCES creative_document_versions (id) ON DELETE CASCADE
);

UPDATE alembic_version SET version_num='0003_creative_documents' WHERE alembic_version.version_num = '0002_local_auth_foundation';

-- Running upgrade 0003_creative_documents -> 0004_composition_studio

CREATE TABLE composition_documents (
    id UUID NOT NULL, 
    workflow_run_id UUID NOT NULL, 
    revision INTEGER DEFAULT '0' NOT NULL, 
    active_version_id UUID, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (workflow_run_id), 
    FOREIGN KEY(workflow_run_id) REFERENCES workflow_runs (id) ON DELETE CASCADE
);

CREATE TABLE composition_versions (
    id UUID NOT NULL, 
    composition_document_id UUID NOT NULL, 
    revision INTEGER NOT NULL, 
    state VARCHAR(24) DEFAULT 'draft' NOT NULL, 
    aspect_ratio VARCHAR(24) DEFAULT '9:16' NOT NULL, 
    canvas_config JSONB DEFAULT '{}'::jsonb NOT NULL, 
    created_by_subject VARCHAR(512) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_composition_revision UNIQUE (composition_document_id, revision), 
    FOREIGN KEY(composition_document_id) REFERENCES composition_documents (id) ON DELETE CASCADE
);

CREATE TABLE composition_tracks (
    id UUID NOT NULL, 
    composition_version_id UUID NOT NULL, 
    position INTEGER NOT NULL, 
    track_type VARCHAR(32) NOT NULL, 
    name VARCHAR(120) NOT NULL, 
    muted BOOLEAN DEFAULT false NOT NULL, 
    locked BOOLEAN DEFAULT false NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_composition_track_position UNIQUE (composition_version_id, position), 
    FOREIGN KEY(composition_version_id) REFERENCES composition_versions (id) ON DELETE CASCADE
);

CREATE TABLE composition_clips (
    id UUID NOT NULL, 
    composition_track_id UUID NOT NULL, 
    position INTEGER NOT NULL, 
    source_type VARCHAR(32) NOT NULL, 
    source_ref VARCHAR(1024) NOT NULL, 
    timeline_start_ms INTEGER NOT NULL, 
    duration_ms INTEGER NOT NULL, 
    trim_in_ms INTEGER DEFAULT '0' NOT NULL, 
    transform JSONB DEFAULT '{}'::jsonb NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_composition_clip_position UNIQUE (composition_track_id, position), 
    FOREIGN KEY(composition_track_id) REFERENCES composition_tracks (id) ON DELETE CASCADE
);

CREATE TABLE composition_effect_instances (
    id UUID NOT NULL, 
    composition_clip_id UUID NOT NULL, 
    position INTEGER NOT NULL, 
    effect_key VARCHAR(120) NOT NULL, 
    config JSONB DEFAULT '{}'::jsonb NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_composition_effect_position UNIQUE (composition_clip_id, position), 
    FOREIGN KEY(composition_clip_id) REFERENCES composition_clips (id) ON DELETE CASCADE
);

CREATE TABLE composition_keyframes (
    id UUID NOT NULL, 
    composition_clip_id UUID NOT NULL, 
    property_key VARCHAR(96) NOT NULL, 
    time_ms INTEGER NOT NULL, 
    value JSONB DEFAULT '{}'::jsonb NOT NULL, 
    easing VARCHAR(48) DEFAULT 'linear' NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_composition_keyframe UNIQUE (composition_clip_id, property_key, time_ms), 
    FOREIGN KEY(composition_clip_id) REFERENCES composition_clips (id) ON DELETE CASCADE
);

UPDATE alembic_version SET version_num='0004_composition_studio' WHERE alembic_version.version_num = '0003_creative_documents';

-- Running upgrade 0004_composition_studio -> 0005_command_receipts_and_audit

CREATE TABLE command_receipts (
    id UUID NOT NULL, 
    organization_id UUID NOT NULL, 
    operation_type VARCHAR(64) NOT NULL, 
    idempotency_key VARCHAR(128) NOT NULL, 
    workflow_run_id UUID NOT NULL, 
    request_fingerprint VARCHAR(64) NOT NULL, 
    result_payload JSONB NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (idempotency_key)
);

CREATE TABLE workflow_audit_events (
    id UUID NOT NULL, 
    organization_id UUID NOT NULL, 
    workflow_run_id UUID NOT NULL, 
    action VARCHAR(64) NOT NULL, 
    actor_subject VARCHAR(512) NOT NULL, 
    target_version_id UUID, 
    trace_id VARCHAR(64) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE, 
    FOREIGN KEY(workflow_run_id) REFERENCES workflow_runs (id) ON DELETE CASCADE
);

UPDATE alembic_version SET version_num='0005_command_receipts_and_audit' WHERE alembic_version.version_num = '0004_composition_studio';

-- Running upgrade 0005_command_receipts_and_audit -> 0006_command_receipts_hardened

ALTER TABLE command_receipts ADD CONSTRAINT fk_command_receipts_org FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE;

ALTER TABLE command_receipts ADD CONSTRAINT fk_command_receipts_workflow_run FOREIGN KEY(workflow_run_id) REFERENCES workflow_runs (id) ON DELETE CASCADE;

ALTER TABLE workflow_audit_events ADD CONSTRAINT fk_workflow_audit_events_target_version FOREIGN KEY(target_version_id) REFERENCES creative_document_versions (id) ON DELETE SET NULL;

CREATE INDEX ix_command_receipts_org_workflow ON command_receipts (organization_id, workflow_run_id);

CREATE INDEX ix_workflow_audit_events_org_workflow_time ON workflow_audit_events (organization_id, workflow_run_id, created_at);

UPDATE alembic_version SET version_num='0006_command_receipts_hardened' WHERE alembic_version.version_num = '0005_command_receipts_and_audit';

-- Running upgrade 0006_command_receipts_hardened -> 0007_add_context_fields

UPDATE alembic_version SET version_num='0007_add_context_fields' WHERE alembic_version.version_num = '0006_command_receipts_hardened';

-- Running upgrade 0007_add_context_fields -> 0008_worker_context_lookup

ALTER TABLE workflow_runs ADD COLUMN legacy_job_id VARCHAR(64);

ALTER TABLE workflow_runs ADD CONSTRAINT uq_workflow_runs_legacy_job_id UNIQUE (legacy_job_id);

UPDATE alembic_version SET version_num='0008_worker_context_lookup' WHERE alembic_version.version_num = '0007_add_context_fields';

-- Running upgrade 0008_worker_context_lookup -> 0009_publisher_connections

CREATE TABLE publisher_connections (
    id UUID NOT NULL, 
    organization_id UUID NOT NULL, 
    provider VARCHAR(32) NOT NULL, 
    provider_account_id VARCHAR(256) NOT NULL, 
    display_name VARCHAR(256) NOT NULL, 
    encrypted_refresh_token TEXT NOT NULL, 
    scopes JSONB DEFAULT '{}'::jsonb NOT NULL, 
    status VARCHAR(32) DEFAULT 'active' NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE, 
    connected_by_subject VARCHAR(512) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_publisher_connection_account UNIQUE (organization_id, provider, provider_account_id), 
    FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE
);

CREATE INDEX ix_publisher_connections_org_provider ON publisher_connections (organization_id, provider);

UPDATE alembic_version SET version_num='0009_publisher_connections' WHERE alembic_version.version_num = '0008_worker_context_lookup';

-- Running upgrade 0009_publisher_connections -> 0010_publisher_oauth_attempts

CREATE TABLE publisher_oauth_attempts (
    id UUID NOT NULL, 
    organization_id UUID NOT NULL, 
    provider VARCHAR(32) NOT NULL, 
    state_digest VARCHAR(64) NOT NULL, 
    requested_by_subject VARCHAR(512) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    consumed_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE, 
    UNIQUE (state_digest)
);

CREATE INDEX ix_publisher_oauth_attempts_expiry ON publisher_oauth_attempts (expires_at);

UPDATE alembic_version SET version_num='0010_publisher_oauth_attempts' WHERE alembic_version.version_num = '0009_publisher_connections';

-- Running upgrade 0010_publisher_oauth_attempts -> 0011_publication_attempts

CREATE TABLE publication_attempts (
    id UUID NOT NULL, 
    workflow_run_id UUID NOT NULL, 
    publisher_connection_id UUID NOT NULL, 
    attempt_number INTEGER NOT NULL, 
    state VARCHAR(32) DEFAULT 'requested' NOT NULL, 
    requested_by_subject VARCHAR(512) NOT NULL, 
    failure_code VARCHAR(96), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_publication_attempt_number UNIQUE (workflow_run_id, attempt_number), 
    FOREIGN KEY(workflow_run_id) REFERENCES workflow_runs (id) ON DELETE CASCADE, 
    FOREIGN KEY(publisher_connection_id) REFERENCES publisher_connections (id) ON DELETE RESTRICT
);

UPDATE alembic_version SET version_num='0011_publication_attempts' WHERE alembic_version.version_num = '0010_publisher_oauth_attempts';

-- Running upgrade 0011_publication_attempts -> 0012_pub_attempt_lease

ALTER TABLE publication_attempts ADD COLUMN lease_token VARCHAR(64);

ALTER TABLE publication_attempts ADD COLUMN lease_expires_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE publication_attempts ADD COLUMN external_video_id VARCHAR(255);

ALTER TABLE publication_attempts ADD COLUMN external_url VARCHAR(2048);

CREATE INDEX ix_publication_attempts_lease_expires_at ON publication_attempts (lease_expires_at);

UPDATE alembic_version SET version_num='0012_pub_attempt_lease' WHERE alembic_version.version_num = '0011_publication_attempts';

-- Running upgrade 0012_pub_attempt_lease -> 0013_one_active_pub_attempt

CREATE UNIQUE INDEX uq_publication_attempts_one_active ON publication_attempts (workflow_run_id) WHERE state IN ('requested', 'claimed');

UPDATE alembic_version SET version_num='0013_one_active_pub_attempt' WHERE alembic_version.version_num = '0012_pub_attempt_lease';

-- Running upgrade 0013_one_active_pub_attempt -> 0014_pub_upload_active

DROP INDEX uq_publication_attempts_one_active;

CREATE UNIQUE INDEX uq_publication_attempts_one_active ON publication_attempts (workflow_run_id) WHERE state IN ('requested', 'claimed', 'uploading');

UPDATE alembic_version SET version_num='0014_pub_upload_active' WHERE alembic_version.version_num = '0013_one_active_pub_attempt';

-- Running upgrade 0014_pub_upload_active -> 0015_provider_credential_vault

CREATE TABLE provider_credentials (
    id UUID NOT NULL, 
    organization_id UUID NOT NULL, 
    provider VARCHAR(64) NOT NULL, 
    label VARCHAR(120) NOT NULL, 
    secret_ciphertext TEXT NOT NULL, 
    secret_fingerprint VARCHAR(64) NOT NULL, 
    priority INTEGER NOT NULL, 
    status VARCHAR(24) DEFAULT 'active' NOT NULL, 
    capabilities JSONB DEFAULT '{}'::jsonb NOT NULL, 
    created_by_subject VARCHAR(512) NOT NULL, 
    last_used_at TIMESTAMP WITH TIME ZONE, 
    last_failure_code VARCHAR(96), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_provider_credential_label UNIQUE (organization_id, provider, label), 
    FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE
);

CREATE INDEX ix_provider_credentials_resolution ON provider_credentials (organization_id, provider, status, priority);

CREATE TABLE provider_credential_audit_events (
    id UUID NOT NULL, 
    organization_id UUID NOT NULL, 
    credential_id UUID, 
    actor_subject VARCHAR(512) NOT NULL, 
    event_type VARCHAR(80) NOT NULL, 
    outcome VARCHAR(24) NOT NULL, 
    metadata_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE, 
    FOREIGN KEY(credential_id) REFERENCES provider_credentials (id) ON DELETE SET NULL
);

CREATE INDEX ix_provider_credential_audit_org_time ON provider_credential_audit_events (organization_id, created_at);

UPDATE alembic_version SET version_num='0015_provider_credential_vault' WHERE alembic_version.version_num = '0014_pub_upload_active';

-- Running upgrade 0015_provider_credential_vault -> 0016_creative_sessions

CREATE TABLE creative_sessions (
    id UUID NOT NULL, 
    organization_id UUID NOT NULL, 
    workflow_run_id UUID, 
    revision INTEGER DEFAULT '0' NOT NULL, 
    creation_spec JSONB NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_creative_session_workflow_run UNIQUE (workflow_run_id), 
    FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE, 
    FOREIGN KEY(workflow_run_id) REFERENCES workflow_runs (id) ON DELETE SET NULL
);

CREATE TABLE creative_messages (
    id UUID NOT NULL, 
    session_id UUID NOT NULL, 
    actor VARCHAR(32) NOT NULL, 
    content TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT chk_creative_message_actor CHECK (actor IN ('user', 'assistant')), 
    FOREIGN KEY(session_id) REFERENCES creative_sessions (id) ON DELETE CASCADE
);

CREATE TABLE creative_proposals (
    id UUID NOT NULL, 
    session_id UUID NOT NULL, 
    message_id UUID NOT NULL, 
    parent_proposal_id UUID, 
    state VARCHAR(24) DEFAULT 'proposed' NOT NULL, 
    title VARCHAR(240) NOT NULL, 
    brief TEXT NOT NULL, 
    script TEXT NOT NULL, 
    scenes JSONB DEFAULT '[]'::jsonb NOT NULL, 
    schema_version INTEGER DEFAULT '1' NOT NULL, 
    version INTEGER NOT NULL, 
    trace_id VARCHAR(64) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    generation_manifest JSONB NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_creative_proposals_version UNIQUE (session_id, version), 
    CONSTRAINT chk_creative_proposal_state CHECK (state IN ('proposed', 'accepted', 'superseded')), 
    FOREIGN KEY(session_id) REFERENCES creative_sessions (id) ON DELETE CASCADE, 
    FOREIGN KEY(message_id) REFERENCES creative_messages (id) ON DELETE CASCADE, 
    FOREIGN KEY(parent_proposal_id) REFERENCES creative_proposals (id) ON DELETE SET NULL
);

CREATE TABLE creative_turns (
    id UUID NOT NULL, 
    session_id UUID NOT NULL, 
    idempotency_key VARCHAR(128) NOT NULL, 
    request_fingerprint VARCHAR(64) NOT NULL, 
    status VARCHAR(24) DEFAULT 'generating' NOT NULL, 
    lease_token UUID NOT NULL, 
    lease_expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    expected_revision INTEGER NOT NULL, 
    user_message_id UUID NOT NULL, 
    assistant_message_id UUID, 
    proposal_id UUID, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    generation_attempt_count INTEGER DEFAULT '1' NOT NULL, 
    failure_code VARCHAR(96), 
    PRIMARY KEY (id), 
    CONSTRAINT uq_creative_turns_session_idempotency UNIQUE (session_id, idempotency_key), 
    CONSTRAINT chk_creative_turn_status CHECK (status IN ('generating', 'completed', 'failed')), 
    FOREIGN KEY(session_id) REFERENCES creative_sessions (id) ON DELETE CASCADE, 
    FOREIGN KEY(user_message_id) REFERENCES creative_messages (id) ON DELETE CASCADE, 
    FOREIGN KEY(assistant_message_id) REFERENCES creative_messages (id) ON DELETE SET NULL, 
    FOREIGN KEY(proposal_id) REFERENCES creative_proposals (id) ON DELETE SET NULL
);

CREATE TABLE creative_command_receipts (
    id UUID NOT NULL, 
    organization_id UUID NOT NULL, 
    session_id UUID, 
    operation_type VARCHAR(64) NOT NULL, 
    idempotency_key VARCHAR(128) NOT NULL, 
    request_fingerprint VARCHAR(64) NOT NULL, 
    result_payload JSONB NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_creative_command_receipts_key UNIQUE (organization_id, operation_type, idempotency_key), 
    FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE, 
    FOREIGN KEY(session_id) REFERENCES creative_sessions (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_active_generating_turn ON creative_turns (session_id) WHERE status = 'generating';

CREATE UNIQUE INDEX uq_accepted_proposal_per_session ON creative_proposals (session_id) WHERE state = 'accepted';

UPDATE alembic_version SET version_num='0016_creative_sessions' WHERE alembic_version.version_num = '0015_provider_credential_vault';

-- Running upgrade 0016_creative_sessions -> 0017_prompt_template_registry

DO $$
DECLARE
    org_id UUID;
    planner_tmpl_id UUID;
    director_tmpl_id UUID;
BEGIN
    FOR org_id IN SELECT id FROM organizations LOOP

        -- ── short_video_scene_planner ────────────────────────────────────────
        INSERT INTO prompt_templates (id, organization_id, prompt_key, name, description, production_version)
        VALUES (
            gen_random_uuid(), org_id,
            'short_video_scene_planner',
            'Short video scene planner',
            'Acts as the scene planning director: breaks down the creative brief and chat context into a structured list of scenes for the short-video renderer.',
            1
        )
        ON CONFLICT (organization_id, prompt_key) DO NOTHING;

        SELECT id INTO planner_tmpl_id
        FROM prompt_templates
        WHERE organization_id = org_id AND prompt_key = 'short_video_scene_planner';

        INSERT INTO prompt_versions (id, prompt_template_id, version, content, config, change_note)
        VALUES (
            gen_random_uuid(), planner_tmpl_id, 1,
            'Bạn là Đạo diễn Phân cảnh của VisionFlow AI. Nhiệm vụ của bạn là đọc hiểu yêu cầu sáng tạo từ người dùng và lịch sử hội thoại, sau đó xây dựng một kịch bản phân cảnh chi tiết cho video ngắn dọc (9:16).

[QUY TẮC BẮT BUỘC]:
1. Mỗi phân cảnh phải có đủ: narration (lời thoại), visual_prompt (mô tả hình ảnh tiếng Anh), duration_seconds (3-20 giây), transition (cut/fade/dissolve/zoom_in/zoom_out), caption (phụ đề hiển thị).
2. Tổng thời lượng các cảnh phải xấp xỉ thời lượng yêu cầu trong creation_spec.
3. Lời thoại (narration) viết bằng ngôn ngữ được chỉ định trong creation_spec, ngắn gọn, thu hút.
4. visual_prompt luôn viết bằng tiếng Anh, mô tả chi tiết: nhân vật, hành động, góc máy, ánh sáng, màu sắc, phong cách.
5. Số lượng phân cảnh từ 3 đến 20 cảnh.
6. Phân bổ thời lượng hợp lý, cảnh mở đầu và kết thúc thường ngắn hơn cảnh giữa.
7. Tone và phong cách phải nhất quán với visual_preset và brief đã cung cấp.',
            '{"model": "gemini-2.5-flash", "temperature": 0.7, "response_mime_type": "application/json"}'::jsonb,
            'Initial baseline prompt seeded by migration 0017.'
        )
        ON CONFLICT (prompt_template_id, version) DO NOTHING;

        -- ── short_video_visual_art_director ──────────────────────────────────
        INSERT INTO prompt_templates (id, organization_id, prompt_key, name, description, production_version)
        VALUES (
            gen_random_uuid(), org_id,
            'short_video_visual_art_director',
            'Short video visual art director',
            'Acts as the visual art director: expands each scene narration into a rich, cinematic English media-search and render prompt.',
            1
        )
        ON CONFLICT (organization_id, prompt_key) DO NOTHING;

        SELECT id INTO director_tmpl_id
        FROM prompt_templates
        WHERE organization_id = org_id AND prompt_key = 'short_video_visual_art_director';

        INSERT INTO prompt_versions (id, prompt_template_id, version, content, config, change_note)
        VALUES (
            gen_random_uuid(), director_tmpl_id, 1,
            'You are the Visual Art Director for VisionFlow AI. Your role is to transform each scene narration and the overall creative brief into a highly detailed, cinematic English visual prompt suitable for AI image/video generation and stock media search.

[MANDATORY RULES]:
1. Always write visual_prompt in English regardless of the video language.
2. Include: subject description, action, camera angle (close-up/wide/medium shot), lighting style, color palette, mood, and the visual_preset theme from the creation spec.
3. Keep the composition optimized for vertical 9:16 short-form video.
4. Ensure visual consistency across all scenes (same characters, color grading, art style).
5. Append technical tags at the end: cinematic lighting, 4K, vertical composition, professional quality.
6. The prompt must be self-contained — do not reference previous scenes by number.
7. Adapt the style to match the format_profile and visual_preset supplied in the creation spec.',
            '{"model": "gemini-2.5-flash", "temperature": 0.4, "response_mime_type": "application/json"}'::jsonb,
            'Initial baseline prompt seeded by migration 0017.'
        )
        ON CONFLICT (prompt_template_id, version) DO NOTHING;

    END LOOP;
END $$;;

UPDATE alembic_version SET version_num='0017_prompt_template_registry' WHERE alembic_version.version_num = '0016_creative_sessions';

-- Running upgrade 0017_prompt_template_registry -> 0018_voice_system

CREATE TABLE voice_settings (
    organization_id UUID NOT NULL, 
    revision INTEGER DEFAULT '0' NOT NULL, 
    config JSONB DEFAULT '{}' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (organization_id), 
    FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE
);

CREATE TABLE voice_lab_samples (
    id UUID NOT NULL, 
    organization_id UUID NOT NULL, 
    state VARCHAR(20) NOT NULL, 
    request JSONB NOT NULL, 
    result JSONB NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE
);

CREATE INDEX ix_voice_lab_samples_organization_id ON voice_lab_samples (organization_id);

UPDATE alembic_version SET version_num='0018_voice_system' WHERE alembic_version.version_num = '0017_prompt_template_registry';

-- Running upgrade 0018_voice_system -> 0019_scene_library

CREATE TABLE source_assets (
    id VARCHAR(64) NOT NULL, 
    source_type VARCHAR(32) DEFAULT 'video' NOT NULL, 
    original_uri TEXT, 
    storage_ref TEXT, 
    fingerprint VARCHAR(128) NOT NULL, 
    duration FLOAT DEFAULT '0.0' NOT NULL, 
    width INTEGER DEFAULT '0' NOT NULL, 
    height INTEGER DEFAULT '0' NOT NULL, 
    fps FLOAT DEFAULT '0.0' NOT NULL, 
    codec VARCHAR(32) DEFAULT 'unknown' NOT NULL, 
    language VARCHAR(16), 
    transcript_state VARCHAR(32) DEFAULT 'PENDING' NOT NULL, 
    rights_state VARCHAR(32) DEFAULT 'UNKNOWN' NOT NULL, 
    watermark_state VARCHAR(32) DEFAULT 'none' NOT NULL, 
    ingest_status VARCHAR(32) DEFAULT 'INGESTED' NOT NULL, 
    analysis_version VARCHAR(32) DEFAULT 'v1' NOT NULL, 
    metadata_json JSONB DEFAULT '{}' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_source_assets_fingerprint ON source_assets (fingerprint);

CREATE TABLE source_scenes (
    id VARCHAR(64) NOT NULL, 
    source_id VARCHAR(64) NOT NULL, 
    start_sec FLOAT NOT NULL, 
    end_sec FLOAT NOT NULL, 
    duration_sec FLOAT NOT NULL, 
    fingerprint VARCHAR(128) NOT NULL, 
    description TEXT, 
    transcript TEXT, 
    entities JSONB DEFAULT '[]' NOT NULL, 
    actions JSONB DEFAULT '[]' NOT NULL, 
    location_context TEXT, 
    shot_type VARCHAR(64), 
    motion_score FLOAT DEFAULT '0.5' NOT NULL, 
    technical_quality_score FLOAT DEFAULT '0.8' NOT NULL, 
    embedding_ref VARCHAR(128), 
    analysis_version VARCHAR(32) DEFAULT 'v1' NOT NULL, 
    keyframes JSONB DEFAULT '[]' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(source_id) REFERENCES source_assets (id) ON DELETE CASCADE
);

CREATE INDEX ix_source_scenes_source_id ON source_scenes (source_id);

CREATE INDEX ix_source_scenes_fingerprint ON source_scenes (fingerprint);

CREATE TABLE scene_embeddings (
    id VARCHAR(64) NOT NULL, 
    scene_id VARCHAR(64) NOT NULL, 
    vector_data JSONB DEFAULT '[]' NOT NULL, 
    text_representation TEXT NOT NULL, 
    model_name VARCHAR(64) NOT NULL, 
    dimensions INTEGER NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(scene_id) REFERENCES source_scenes (id) ON DELETE CASCADE
);

CREATE INDEX ix_scene_embeddings_scene_id ON scene_embeddings (scene_id);

UPDATE alembic_version SET version_num='0019_scene_library' WHERE alembic_version.version_num = '0018_voice_system';

-- Running upgrade 0019_scene_library -> 0020_retrieval_hardening

ALTER TABLE source_assets ADD COLUMN fast_fingerprint VARCHAR(128);

CREATE INDEX ix_source_assets_fast_fingerprint ON source_assets (fast_fingerprint);

ALTER TABLE source_scenes ADD COLUMN visual_fingerprint VARCHAR(128);

CREATE INDEX ix_source_scenes_visual_fingerprint ON source_scenes (visual_fingerprint);

ALTER TABLE scene_embeddings ADD COLUMN provider VARCHAR(32) DEFAULT 'local' NOT NULL;

ALTER TABLE scene_embeddings ADD COLUMN model VARCHAR(64) DEFAULT 'hashed-lexical-v1' NOT NULL;

ALTER TABLE scene_embeddings ADD COLUMN embedding_version VARCHAR(32) DEFAULT 'v1' NOT NULL;

CREATE INDEX ix_scene_embeddings_version_lookup ON scene_embeddings (provider, model, dimensions, embedding_version);

UPDATE alembic_version SET version_num='0020_retrieval_hardening' WHERE alembic_version.version_num = '0019_scene_library';

-- Running upgrade 0020_retrieval_hardening -> 0021_remote_render_workers

CREATE TABLE render_workers (
    worker_id VARCHAR(120) NOT NULL, 
    worker_type VARCHAR(48) NOT NULL, 
    status VARCHAR(24) NOT NULL, 
    platform VARCHAR(32) NOT NULL, 
    renderer_version VARCHAR(80) NOT NULL, 
    ffmpeg_version VARCHAR(160) NOT NULL, 
    capabilities JSONB NOT NULL, 
    max_concurrent_jobs INTEGER NOT NULL, 
    last_heartbeat_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (worker_id)
);

CREATE TABLE render_jobs (
    id UUID NOT NULL, 
    run_id VARCHAR(128) NOT NULL, 
    status VARCHAR(32) NOT NULL, 
    priority INTEGER NOT NULL, 
    render_spec_version VARCHAR(48) NOT NULL, 
    render_spec_json JSONB NOT NULL, 
    render_input_hash VARCHAR(64) NOT NULL, 
    attempt INTEGER NOT NULL, 
    max_attempts INTEGER NOT NULL, 
    claimed_by_worker_id VARCHAR(120), 
    lease_expires_at TIMESTAMP WITH TIME ZONE, 
    last_heartbeat_at TIMESTAMP WITH TIME ZONE, 
    completed_at TIMESTAMP WITH TIME ZONE, 
    failed_at TIMESTAMP WITH TIME ZONE, 
    error_code VARCHAR(80), 
    error_message TEXT, 
    retryable BOOLEAN NOT NULL, 
    output_artifact_ref VARCHAR(1024), 
    idempotency_key VARCHAR(128) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(claimed_by_worker_id) REFERENCES render_workers (worker_id), 
    UNIQUE (idempotency_key)
);

CREATE INDEX ix_render_jobs_claimable ON render_jobs (status, priority, created_at);

UPDATE alembic_version SET version_num='0021_remote_render_workers' WHERE alembic_version.version_num = '0020_retrieval_hardening';

-- Running upgrade 0021_remote_render_workers -> 0022_channel_learning_metrics

CREATE TABLE channel_learning_metrics (
    id UUID NOT NULL, 
    organization_id UUID NOT NULL, 
    channel_handle VARCHAR(120) NOT NULL, 
    publication_attempt_id UUID, 
    views_count INTEGER DEFAULT '0' NOT NULL, 
    completion_rate FLOAT DEFAULT '0' NOT NULL, 
    likes_count INTEGER DEFAULT '0' NOT NULL, 
    shares_count INTEGER DEFAULT '0' NOT NULL, 
    average_watch_time_sec FLOAT DEFAULT '0' NOT NULL, 
    video_metadata_snapshot JSONB DEFAULT '{}'::jsonb NOT NULL, 
    ai_winning_formula JSONB DEFAULT '{}'::jsonb NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE CASCADE, 
    FOREIGN KEY(publication_attempt_id) REFERENCES publication_attempts (id) ON DELETE SET NULL
);

CREATE INDEX ix_channel_learnings_org_handle ON channel_learning_metrics (organization_id, channel_handle);

UPDATE alembic_version SET version_num='0022_channel_learning_metrics' WHERE alembic_version.version_num = '0021_remote_render_workers';

COMMIT;

